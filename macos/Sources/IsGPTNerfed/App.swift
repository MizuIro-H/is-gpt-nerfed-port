import AppKit
import SwiftUI

// MARK: - Menu bar item: the inspector's face as text. Neutral normally, orange when suspicious, red on a
// confirmed downgrade. Text instead of a glyph so the state is readable at a glance and matches the panel header.

enum MenuBarFace {
    static func face(alert: Bool, warn: Bool, running: Bool) -> String {
        if alert { return "(ಠ_ಠ)" }
        if warn { return "(•_•)" }
        if running { return "(•o•)" }
        return "(•ᴗ•)"
    }

    static func color(alert: Bool, warn: Bool) -> Color {
        alert ? .red : (warn ? .orange : .primary)
    }

    static func label(alert: Bool, warn: Bool, running: Bool) -> some View {
        Text(face(alert: alert, warn: warn, running: running))
            .font(.system(size: 12, weight: .semibold, design: .rounded))
            .foregroundStyle(color(alert: alert, warn: warn))
    }
}

// MARK: - App delegate (accessory app; --preview opens the panel in a window; --render writes self-portraits)

final class AppDelegate: NSObject, NSApplicationDelegate {
    var previewWindow: NSWindow?

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApplication.shared.setActivationPolicy(.accessory)
        let args = CommandLine.arguments
        if let i = args.firstIndex(of: "--render"), i + 1 < args.count {
            render(to: args[i + 1])
            return
        }
        if args.contains("--preview") {
            let hosting = NSHostingController(rootView: PanelView().environment(Store.shared))
            let window = NSWindow(contentViewController: hosting)
            window.title = "is-gpt-nerfed"
            window.styleMask = [.titled, .closable]
            window.setFrameOrigin(NSPoint(x: 80, y: 120))
            window.makeKeyAndOrderFront(nil)
            NSApplication.shared.activate(ignoringOtherApps: true)
            previewWindow = window
        }
    }

    /// Headless self-portraits for the README (ImageRenderer cannot composite Liquid Glass, so the panel renders
    /// with its flat fallback): the panel, and the panel with a session opened.
    private func render(to path: String) {
        Task { @MainActor in
            let store = Store.shared
            for _ in 0..<40 where store.snapshot == nil {
                await store.refresh()
                try? await Task.sleep(for: .milliseconds(250))
            }
            let variants: [(String, Bool, String?)] = [("", false, nil), ("-detail", false, "payments")]
            for (suffix, settings, open) in variants {
                let renderer = ImageRenderer(content: PanelView(showSettings: settings, open: open).environment(store).environment(\.plainRendering, true)
                                                .frame(width: 440).padding(8).background(Color(nsColor: .windowBackgroundColor)))
                renderer.scale = 2
                if let img = renderer.nsImage, let tiff = img.tiffRepresentation, let rep = NSBitmapImageRep(data: tiff),
                   let png = rep.representation(using: .png, properties: [:]) {
                    try? png.write(to: URL(fileURLWithPath: path.replacingOccurrences(of: ".png", with: "\(suffix).png")))
                }
            }
            NSApplication.shared.terminate(nil)
        }
    }
}

// MARK: - App

@main
struct IsGPTNerfedApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate
    private let store = Store.shared

    init() {
        Store.shared.start()
    }

    var body: some Scene {
        MenuBarExtra {
            PanelView().environment(store)
        } label: {
            MenuBarFace.label(alert: store.isAlert, warn: store.isWarn, running: store.isRunning)
        }
        .menuBarExtraStyle(.window)
    }
}
