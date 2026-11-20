// WinUI 3 inspector: renders the state the Python tray app streams on stdin and reports clicks on stdout.
// All behaviour (what is enabled, wording, scheduling, the core itself) is decided in desktop/winui_bridge.py.
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading;
using Microsoft.UI;
using Microsoft.UI.Dispatching;
using Microsoft.UI.Text;
using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Media.Imaging;
using Windows.ApplicationModel.DataTransfer;

namespace IsGPTNerfed.Inspector;

public static class Program
{
    [STAThread]
    public static void Main()
    {
        WinRT.ComWrappersSupport.InitializeComWrappers();
        Application.Start(p =>
        {
            var context = new DispatcherQueueSynchronizationContext(DispatcherQueue.GetForCurrentThread());
            SynchronizationContext.SetSynchronizationContext(context);
            new App();
        });
    }
}

// Without XAML pages nothing generates the metadata provider, and XamlControlsResources cannot resolve the
// WinUI control types/themes it references; delegate to the controls library's own provider.
public sealed class App : Application, Microsoft.UI.Xaml.Markup.IXamlMetadataProvider
{
    InspectorWindow? window;
    readonly Microsoft.UI.Xaml.XamlTypeInfo.XamlControlsXamlMetaDataProvider controls = new();

    public Microsoft.UI.Xaml.Markup.IXamlType GetXamlType(Type type) => controls.GetXamlType(type);
    public Microsoft.UI.Xaml.Markup.IXamlType GetXamlType(string fullName) => controls.GetXamlType(fullName);
    public Microsoft.UI.Xaml.Markup.XmlnsDefinition[] GetXmlnsDefinitions() => controls.GetXmlnsDefinitions();

    public App()
    {
        UnhandledException += (_, e) => Crash(e.Exception);
    }

    protected override void OnLaunched(LaunchActivatedEventArgs args)
    {
        try
        {
            Resources.MergedDictionaries.Add(new XamlControlsResources());
            window = new InspectorWindow();
            window.Start();
        }
        catch (Exception e)
        {
            Crash(e);
            throw;
        }
    }

    // stderr is captured by the tray app; also keep a file for when it is not.
    internal static void Crash(Exception e)
    {
        var text = $"{DateTime.Now:o} {e}\n";
        try { Console.Error.Write(text); } catch { }
        try { File.AppendAllText(Path.Combine(Path.GetTempPath(), "IsGPTNerfed.Inspector.log"), text); } catch { }
    }
}

sealed class InspectorWindow : Window
{
    readonly DispatcherQueue ui = DispatcherQueue.GetForCurrentThread();
    readonly Stream stdout = Console.OpenStandardOutput();
    Dictionary<string, string> s = new();
    JsonObject state = new();
    string selectedId = "";
    string threadsSignature = "";
    bool closing;

    // chrome
    readonly Image titleIcon = new() { Width = 16, Height = 16, Margin = new Thickness(0, 0, 10, 0) };
    readonly TextBlock titleText = new() { VerticalAlignment = VerticalAlignment.Center, Style = Style("CaptionTextBlockStyle") };
    readonly TextBlock headline = new() { Style = Style("SubtitleTextBlockStyle"), TextWrapping = TextWrapping.NoWrap, TextTrimming = TextTrimming.CharacterEllipsis };
    readonly TextBlock substatus = new() { Style = Style("CaptionTextBlockStyle"), IsTextSelectionEnabled = true, Opacity = 0.75 };
    readonly Button refreshButton = IconButton("\uE72C");
    readonly Button settingsButton = IconButton("\uE713");
    readonly Button exitButton = IconButton("\uE7E8");
    readonly InfoBar errorBar = new() { Severity = InfoBarSeverity.Error, IsOpen = false, Margin = new Thickness(0, 8, 0, 0) };
    readonly InfoBar demoBar = new() { Severity = InfoBarSeverity.Warning, IsOpen = false, IsClosable = false, Margin = new Thickness(0, 8, 0, 0) };
    readonly SelectorBar tabs = new();
    readonly Grid pages = new();

    // sessions
    readonly ListView threadList = new() { SelectionMode = ListViewSelectionMode.Single };
    readonly Grid threadHeader = new() { Padding = new Thickness(12, 0, 12, 6) };
    readonly TextBlock emptyText = new() { Opacity = 0.6, Margin = new Thickness(16, 12, 0, 0), Visibility = Visibility.Collapsed };
    readonly TextBox report = ReadOnlyBox();
    readonly TextBox history = ReadOnlyBox();
    readonly TextBlock reportLabel = Caption();
    readonly TextBlock historyLabel = Caption();
    readonly Button probeButton = new() { Style = Style("AccentButtonStyle") };
    readonly Button retryButton = new();
    readonly Button resumeButton = new();
    readonly Button copyButton = new();

    // fresh
    readonly TextBlock freshHint = new() { TextWrapping = TextWrapping.Wrap, Opacity = 0.8 };
    readonly TextBox modelBox = new() { MinWidth = 260 };
    readonly ComboBox effortBox = new() { IsEditable = true, MinWidth = 160 };
    readonly Button freshButton = new() { Style = Style("AccentButtonStyle") };
    readonly TextBox globalReport = ReadOnlyBox();

    // plugin
    readonly TextBlock pluginHint = new() { TextWrapping = TextWrapping.Wrap, Opacity = 0.8 };
    readonly Button installButton = new() { Style = Style("AccentButtonStyle") };
    readonly Button trustButton = new();
    readonly TextBox pluginStatus = ReadOnlyBox();
    readonly TextBox activity = ReadOnlyBox();
    readonly TextBlock statusLabel = Caption();
    readonly TextBlock activityLabel = Caption();

    static readonly double[] Columns = { 3, 1.4, 0.9, 1.1, 3 };

    [System.Runtime.InteropServices.DllImport("user32.dll")]
    static extern uint GetDpiForWindow(IntPtr hwnd);

    [System.Runtime.InteropServices.DllImport("user32.dll")]
    static extern bool SetForegroundWindow(IntPtr hwnd);

    public InspectorWindow()
    {
        if (Microsoft.UI.Composition.SystemBackdrops.MicaController.IsSupported())
            SystemBackdrop = new MicaBackdrop();
        ExtendsContentIntoTitleBar = true;
        AppWindow.TitleBar.PreferredHeightOption = TitleBarHeightOption.Tall;
        // AppWindow sizes are physical pixels: scale the design size by the monitor's DPI.
        var scale = GetDpiForWindow(WinRT.Interop.WindowNative.GetWindowHandle(this)) / 96.0;
        if (scale <= 0) scale = 1;
        AppWindow.Resize(new Windows.Graphics.SizeInt32((int)(1100 * scale), (int)(780 * scale)));
        if (AppWindow.Presenter is OverlappedPresenter presenter)
        {
            presenter.PreferredMinimumWidth = (int)(760 * scale);
            presenter.PreferredMinimumHeight = (int)(560 * scale);
        }
        var ico = Path.Combine(AppContext.BaseDirectory, "IsGPTNerfed.ico");
        if (File.Exists(ico)) AppWindow.SetIcon(ico);
        AppWindow.Closing += (_, e) =>
        {
            if (closing) return;
            e.Cancel = true;      // the tray app lives on; closing just tucks the inspector away
            AppWindow.Hide();
        };
        Content = BuildLayout();
        WireActions();
    }

    public void Start()
    {
        var reader = new Thread(ReadLoop) { IsBackground = true, Name = "stdin" };
        reader.Start();
        Send(new JsonObject { ["action"] = "ready" });
    }

    // ------------------------------------------------------------------ layout

    UIElement BuildLayout()
    {
        var root = new Grid();
        if (!Microsoft.UI.Composition.SystemBackdrops.MicaController.IsSupported())
            root.Background = Brush("ApplicationPageBackgroundThemeBrush");
        root.RowDefinitions.Add(new RowDefinition { Height = new GridLength(48) });
        root.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        root.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });

        var titleBar = new StackPanel { Orientation = Orientation.Horizontal, Padding = new Thickness(16, 0, 0, 0), VerticalAlignment = VerticalAlignment.Center };
        titleBar.Children.Add(titleIcon);
        titleBar.Children.Add(titleText);
        var drag = new Grid { Background = new SolidColorBrush(Colors.Transparent) };
        drag.Children.Add(titleBar);
        root.Children.Add(drag);
        SetTitleBar(drag);

        var header = new Grid { Padding = new Thickness(24, 4, 24, 8) };
        header.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        header.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        var heading = new StackPanel { Spacing = 2 };
        heading.Children.Add(headline);
        heading.Children.Add(substatus);
        header.Children.Add(heading);
        var buttons = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 8, VerticalAlignment = VerticalAlignment.Top };
        buttons.Children.Add(refreshButton);
        buttons.Children.Add(settingsButton);
        buttons.Children.Add(exitButton);
        Grid.SetColumn(buttons, 1);
        header.Children.Add(buttons);
        var top = new StackPanel();
        top.Children.Add(header);
        var bars = new StackPanel { Padding = new Thickness(24, 0, 24, 0) };
        bars.Children.Add(demoBar);
        bars.Children.Add(errorBar);
        top.Children.Add(bars);
        top.Children.Add(new Border { Padding = new Thickness(16, 4, 16, 0), Child = tabs });
        Grid.SetRow(top, 1);
        root.Children.Add(top);

        var card = new Border
        {
            Background = Brush("LayerFillColorDefaultBrush"),
            BorderBrush = Brush("CardStrokeColorDefaultBrush"),
            BorderThickness = new Thickness(0, 1, 0, 0),
            CornerRadius = new CornerRadius(8, 8, 0, 0),
            Padding = new Thickness(24, 16, 24, 16),
            Child = pages,
        };
        Grid.SetRow(card, 2);
        root.Children.Add(card);

        pages.Children.Add(SessionsPage());
        pages.Children.Add(FreshPage());
        pages.Children.Add(PluginPage());
        for (int i = 0; i < 3; i++) tabs.Items.Add(new SelectorBarItem());
        tabs.SelectionChanged += (_, _) => ShowPage(tabs.Items.IndexOf(tabs.SelectedItem));
        tabs.SelectedItem = tabs.Items[0];
        ShowPage(0);
        return root;
    }

    UIElement SessionsPage()
    {
        var g = new Grid { RowSpacing = 12 };
        g.RowDefinitions.Add(new RowDefinition { Height = new GridLength(3, GridUnitType.Star), MinHeight = 160 });
        g.RowDefinitions.Add(new RowDefinition { Height = new GridLength(2, GridUnitType.Star), MinHeight = 120 });
        g.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });

        foreach (var w in Columns) threadHeader.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(w, GridUnitType.Star) });
        for (int i = 0; i < Columns.Length; i++)
        {
            var t = Caption();
            t.TextWrapping = TextWrapping.NoWrap;
            t.TextTrimming = TextTrimming.CharacterEllipsis;
            t.Margin = new Thickness(0, 0, 12, 0);
            Grid.SetColumn(t, i);
            threadHeader.Children.Add(t);
        }
        var listArea = new Grid();
        listArea.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        listArea.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });
        listArea.Children.Add(threadHeader);
        var listHost = new Grid();
        listHost.Children.Add(threadList);
        listHost.Children.Add(emptyText);
        Grid.SetRow(listHost, 1);
        listArea.Children.Add(listHost);
        g.Children.Add(Surface(listArea, new Thickness(0, 10, 0, 4)));

        var details = new Grid { ColumnSpacing = 12 };
        details.ColumnDefinitions.Add(new ColumnDefinition());
        details.ColumnDefinitions.Add(new ColumnDefinition());
        details.Children.Add(Labeled(reportLabel, report));
        var h = Labeled(historyLabel, history);
        Grid.SetColumn(h, 1);
        details.Children.Add(h);
        Grid.SetRow(details, 1);
        g.Children.Add(details);

        var actions = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 8 };
        actions.Children.Add(probeButton);
        actions.Children.Add(retryButton);
        actions.Children.Add(resumeButton);
        actions.Children.Add(copyButton);
        Grid.SetRow(actions, 2);
        g.Children.Add(actions);
        return g;
    }

    UIElement FreshPage()
    {
        var g = new Grid { RowSpacing = 12 };
        g.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        g.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        g.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });
        g.Children.Add(freshHint);
        foreach (var e in new[] { "", "minimal", "low", "medium", "high", "xhigh", "max" }) effortBox.Items.Add(e);
        var row = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 8 };
        row.Children.Add(modelBox);
        row.Children.Add(effortBox);
        row.Children.Add(freshButton);
        Grid.SetRow(row, 1);
        g.Children.Add(row);
        Grid.SetRow(globalReport, 2);
        g.Children.Add(globalReport);
        return g;
    }

    UIElement PluginPage()
    {
        var g = new Grid { RowSpacing = 12 };
        g.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        g.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        g.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });
        g.Children.Add(pluginHint);
        var row = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 8 };
        row.Children.Add(installButton);
        row.Children.Add(trustButton);
        Grid.SetRow(row, 1);
        g.Children.Add(row);
        var split = new Grid { ColumnSpacing = 12 };
        split.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(2, GridUnitType.Star) });
        split.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(3, GridUnitType.Star) });
        split.Children.Add(Labeled(statusLabel, pluginStatus));
        var a = Labeled(activityLabel, activity);
        Grid.SetColumn(a, 1);
        split.Children.Add(a);
        Grid.SetRow(split, 2);
        g.Children.Add(split);
        return g;
    }

    void ShowPage(int index)
    {
        for (int i = 0; i < pages.Children.Count; i++)
            pages.Children[i].Visibility = i == index ? Visibility.Visible : Visibility.Collapsed;
    }

    void WireActions()
    {
        refreshButton.Click += (_, _) => Act("refresh");
        settingsButton.Click += (_, _) => Act("settings");
        exitButton.Click += (_, _) => Act("exit");
        probeButton.Click += (_, _) => Act("probe", selectedId);
        retryButton.Click += (_, _) => Act("retry", selectedId);
        resumeButton.Click += (_, _) => Act("resume", selectedId);
        copyButton.Click += (_, _) =>
        {
            try
            {
                var package = new DataPackage();
                package.SetText(report.Text);
                Clipboard.SetContent(package);
                substatus.Text = T("copied");
            }
            catch (Exception ex)
            {
                errorBar.Message = ex.Message;
                errorBar.IsOpen = true;
            }
        };
        effortBox.SelectionChanged += (_, _) =>
        {
            if (effortBox.SelectedItem is string val)
                effortBox.Text = val;
        };
        freshButton.Click += (_, _) =>
        {
            freshButton.IsEnabled = false;
            var effort = string.IsNullOrWhiteSpace(effortBox.Text)
                ? (effortBox.SelectedItem?.ToString()?.Trim() ?? "")
                : effortBox.Text.Trim();
            Send(new JsonObject { ["action"] = "fresh", ["model"] = modelBox.Text, ["effort"] = effort });
        };
        installButton.Click += (_, _) => { installButton.IsEnabled = false; Act("install"); };
        trustButton.Click += (_, _) => { trustButton.IsEnabled = false; Act("trust"); };
        threadList.SelectionChanged += (_, _) =>
        {
            if (threadList.SelectedItem is ListViewItem item && item.Tag is string id)
            {
                selectedId = id;
                ShowSelected();
            }
        };
    }

    // ------------------------------------------------------------------ protocol

    void ReadLoop()
    {
        using var input = new StreamReader(Console.OpenStandardInput(), new UTF8Encoding(false));
        string? line;
        while ((line = input.ReadLine()) != null)
        {
            JsonObject? message;
            try { message = JsonNode.Parse(line) as JsonObject; }
            catch (JsonException) { continue; }
            if (message != null) ui.TryEnqueue(() => Handle(message));
        }
        // The tray app went away (or quit): follow it.
        ui.TryEnqueue(() => { closing = true; Application.Current.Exit(); });
    }

    void Handle(JsonObject m)
    {
        try
        {
            switch ((string?)m["type"])
            {
                case "init":
                    s = m["strings"]?.AsObject().ToDictionary(kv => kv.Key, kv => (string?)kv.Value ?? "") ?? new();
                    var icon = (string?)m["icon"];
                    if (!string.IsNullOrEmpty(icon) && File.Exists(icon)) titleIcon.Source = new BitmapImage(new Uri(icon));
                    ApplyStrings();
                    break;
                case "state":
                    state = m;
                    Render();
                    break;
                case "show":
                    var thread = (string?)m["thread"];
                    if (!string.IsNullOrEmpty(thread))
                    {
                        selectedId = thread;
                        tabs.SelectedItem = tabs.Items[0];
                        SelectRow();
                    }
                    // 若窗口处于最小化状态，先还原再激活并置前。
                    if (AppWindow.Presenter is OverlappedPresenter p && p.State == OverlappedPresenterState.Minimized)
                        p.Restore();
                    AppWindow.Show();
                    Activate();
                    SetForegroundWindow(WinRT.Interop.WindowNative.GetWindowHandle(this));
                    break;
                case "log":
                    var combined = (activity.Text.Length > 0 ? activity.Text + "\n" : "") + ((string?)m["text"] ?? "");
                    if (combined.Length > 40000)
                        combined = combined[^40000..];
                    activity.Text = combined;
                    activity.SelectionStart = activity.Text.Length;
                    break;
                case "error":
                    errorBar.Message = (string?)m["text"] ?? "";
                    errorBar.IsOpen = true;
                    break;
            }
        }
        catch (Exception ex)
        {
            App.Crash(ex);
            errorBar.Message = ex.Message;
            errorBar.IsOpen = true;
        }
    }

    void Act(string action, string? thread = null)
    {
        var o = new JsonObject { ["action"] = action };
        if (thread != null) o["thread"] = thread;
        Send(o);
    }

    void Send(JsonObject message)
    {
        var bytes = Encoding.UTF8.GetBytes(message.ToJsonString() + "\n");
        try { stdout.Write(bytes); stdout.Flush(); }
        catch (IOException) { closing = true; Application.Current.Exit(); }
    }

    // ------------------------------------------------------------------ rendering

    string T(string key) => s.TryGetValue(key, out var v) ? v : key;

    void ApplyStrings()
    {
        Title = titleText.Text = T("title");
        SetLabel(refreshButton, T("refresh"));
        SetLabel(settingsButton, T("settings"));
        SetLabel(exitButton, T("exit"));
        string[] tabKeys = { "sessions", "fresh_tab", "plugin" };
        for (int i = 0; i < 3; i++) ((SelectorBarItem)tabs.Items[i]).Text = T(tabKeys[i]);
        string[] cols = { "col_session", "col_model", "col_effort", "col_state", "col_evidence" };
        for (int i = 0; i < cols.Length; i++) ((TextBlock)threadHeader.Children[i]).Text = T(cols[i]);
        reportLabel.Text = T("report");
        historyLabel.Text = T("history");
        report.PlaceholderText = T("report_placeholder");
        history.PlaceholderText = T("history_placeholder");
        probeButton.Content = T("probe");
        retryButton.Content = T("retry");
        resumeButton.Content = T("resume");
        copyButton.Content = T("copy");
        freshHint.Text = T("fresh_hint");
        modelBox.PlaceholderText = T("model_placeholder");
        effortBox.PlaceholderText = T("effort_placeholder");
        freshButton.Content = T("fresh");
        pluginHint.Text = T("plugin_hint");
        installButton.Content = T("install");
        trustButton.Content = T("trust");
        statusLabel.Text = T("status");
        activityLabel.Text = T("activity");
        errorBar.Title = T("error_title");
        demoBar.Message = T("demo");
        emptyText.Text = T("empty");
    }

    void Render()
    {
        headline.Text = Str("headline");
        ToolTipService.SetToolTip(headline, headline.Text);
        headline.Foreground = (Str("status")) switch
        {
            "alert" => Brush("SystemFillColorCriticalBrush"),
            "warn" => Brush("SystemFillColorCautionBrush"),
            "ok" or "upgraded" => Brush("SystemFillColorSuccessBrush"),
            _ => Brush("TextFillColorPrimaryBrush"),
        };
        substatus.Text = Str("substatus");
        demoBar.IsOpen = Bool("demo");
        settingsButton.IsEnabled = Bool("settings_enabled");
        freshButton.IsEnabled = Bool("fresh_enabled");
        installButton.IsEnabled = Bool("setup_enabled");
        trustButton.IsEnabled = Bool("trust_enabled");
        SetIfChanged(globalReport, Str("global_report"));
        SetIfChanged(pluginStatus, Str("plugin_status"));

        var threads = Threads();
        var idSig = string.Join("\u0001", threads.Select(t => (string?)t["id"] ?? ""));
        if (idSig != threadsSignature || threadList.Items.Count != threads.Count)
        {
            threadsSignature = idSig;
            threadList.Items.Clear();
            foreach (var t in threads) threadList.Items.Add(Row(t));
            emptyText.Visibility = threads.Count == 0 ? Visibility.Visible : Visibility.Collapsed;
        }
        else
        {
            // 列表顺序未变时原地更新单元格，避免每 8 秒轮询重置滚动位置。
            for (int i = 0; i < threads.Count; i++)
                if (threadList.Items[i] is ListViewItem item)
                    UpdateRow(item, threads[i]);
        }
        if (threads.All(t => (string?)t["id"] != selectedId)) selectedId = threads.Count > 0 ? (string?)threads[0]["id"] ?? "" : "";
        SelectRow();
        ShowSelected();
    }

    static readonly string[] RowKeys = { "title", "model", "effort", "state", "evidence" };

    ListViewItem Row(JsonObject t)
    {
        var g = new Grid { Padding = new Thickness(0, 6, 0, 6) };
        foreach (var w in Columns) g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(w, GridUnitType.Star) });
        for (int i = 0; i < RowKeys.Length; i++)
        {
            var cell = new TextBlock { TextTrimming = TextTrimming.CharacterEllipsis, Margin = new Thickness(0, 0, 12, 0) };
            if (i == 0) cell.FontWeight = FontWeights.SemiBold;
            if (i == 4) cell.Opacity = 0.75;
            Grid.SetColumn(cell, i);
            g.Children.Add(cell);
        }
        var item = new ListViewItem
        {
            Content = g,
            Tag = (string?)t["id"],
            Padding = new Thickness(12, 0, 12, 0),
            HorizontalContentAlignment = HorizontalAlignment.Stretch,
        };
        UpdateRow(item, t);
        return item;
    }

    void UpdateRow(ListViewItem item, JsonObject t)
    {
        item.Tag = (string?)t["id"];
        if (item.Content is not Grid g) return;
        for (int i = 0; i < RowKeys.Length && i < g.Children.Count; i++)
        {
            if (g.Children[i] is not TextBlock cell) continue;
            var text = (string?)t[RowKeys[i]] ?? "";
            if (cell.Text != text)
            {
                cell.Text = text;
                ToolTipService.SetToolTip(cell, string.IsNullOrEmpty(text) ? null : text);
            }
            if (i == 0 || i == 3)
            {
                if ((bool?)t["alert"] == true) cell.Foreground = Brush("SystemFillColorCriticalBrush");
                else if ((bool?)t["suspicious"] == true) cell.Foreground = Brush("SystemFillColorCautionBrush");
                else cell.Foreground = Brush("TextFillColorPrimaryBrush");
            }
        }
    }

    void SelectRow()
    {
        foreach (var o in threadList.Items)
            if (o is ListViewItem item && (string?)item.Tag == selectedId)
            {
                if (!ReferenceEquals(threadList.SelectedItem, item)) threadList.SelectedItem = item;
                return;
            }
    }

    void ShowSelected()
    {
        var t = Threads().FirstOrDefault(x => (string?)x["id"] == selectedId);
        SetIfChanged(report, t == null ? "" : (string?)t["report"] ?? "");
        SetIfChanged(history, t == null ? "" : (string?)t["history"] ?? "");
        probeButton.IsEnabled = t != null && (bool?)t["can_probe"] == true;
        retryButton.IsEnabled = t != null && (bool?)t["can_retry"] == true;
        resumeButton.IsEnabled = t != null && (bool?)t["can_resume"] == true;
        copyButton.IsEnabled = t != null && report.Text.Length > 0;
    }

    List<JsonObject> Threads() =>
        (state["threads"] as JsonArray)?.OfType<JsonObject>().ToList() ?? new List<JsonObject>();

    string Str(string key) => (string?)state[key] ?? "";
    bool Bool(string key) => (bool?)state[key] == true;

    static void SetIfChanged(TextBox box, string text)
    {
        if (box.Text != text) box.Text = text;   // keeps the user's scroll/selection between polls
    }

    // ------------------------------------------------------------------ small factories

    static Style Style(string key) => (Style)Application.Current.Resources[key];
    static Brush Brush(string key) => (Brush)Application.Current.Resources[key];

    static TextBlock Caption() => new() { Style = Style("BodyStrongTextBlockStyle"), Opacity = 0.8 };

    static TextBox ReadOnlyBox()
    {
        var box = new TextBox
        {
            IsReadOnly = true,
            AcceptsReturn = true,
            TextWrapping = TextWrapping.Wrap,
            FontFamily = new FontFamily("Cascadia Mono, Consolas, Microsoft YaHei UI"),
            FontSize = 12.5,
            VerticalAlignment = VerticalAlignment.Stretch,
            HorizontalAlignment = HorizontalAlignment.Stretch,
        };
        ScrollViewer.SetVerticalScrollBarVisibility(box, ScrollBarVisibility.Auto);
        ScrollViewer.SetVerticalScrollMode(box, ScrollMode.Enabled);
        ScrollViewer.SetHorizontalScrollBarVisibility(box, ScrollBarVisibility.Disabled);
        return box;
    }

    static Grid Labeled(TextBlock label, FrameworkElement body)
    {
        var g = new Grid { RowSpacing = 6 };
        g.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        g.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });
        g.Children.Add(label);
        Grid.SetRow(body, 1);
        g.Children.Add(body);
        return g;
    }

    static Border Surface(UIElement child, Thickness padding) => new()
    {
        Background = Brush("CardBackgroundFillColorDefaultBrush"),
        BorderBrush = Brush("CardStrokeColorDefaultBrush"),
        BorderThickness = new Thickness(1),
        CornerRadius = new CornerRadius(8),
        Padding = padding,
        Child = child,
    };

    static Button IconButton(string glyph)
    {
        var b = new Button();
        b.Tag = glyph;
        return b;
    }

    static void SetLabel(Button b, string text)
    {
        var p = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 8 };
        p.Children.Add(new FontIcon { Glyph = (string)b.Tag, FontSize = 14 });
        p.Children.Add(new TextBlock { Text = text });
        b.Content = p;
    }
}
