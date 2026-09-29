import Foundation

enum DGCError: LocalizedError {
    case notFound
    case failed(String)

    var errorDescription: String? {
        switch self {
        case .notFound: return L10n.tr("nerfed not found: the app bundle is incomplete. Rebuild with macos/build.sh or run ./install.sh from a checkout.")
        case .failed(let msg): return msg
        }
    }
}

/// Thin bridge to the `nerfed` Python CLI. All logic stays in the plugin; the app only renders and dispatches.
enum DGC {
    static let home = FileManager.default.homeDirectoryForCurrentUser.path

    static func locate() -> String? {
        let fm = FileManager.default
        if let env = ProcessInfo.processInfo.environment["NERFED_BIN"], fm.fileExists(atPath: env) { return env }
        if let hint = try? String(contentsOfFile: home + "/.codex/is-gpt-nerfed/nerfed_bin", encoding: .utf8) {
            let p = hint.trimmingCharacters(in: .whitespacesAndNewlines)
            if fm.fileExists(atPath: p) { return p }
        }
        // the plugin travels inside the app bundle, so a downloaded .app works before anything is installed
        if let res = Bundle.main.resourcePath {
            let bundled = res + "/marketplace/plugin/skills/is-gpt-nerfed/scripts/nerfed"
            if fm.fileExists(atPath: bundled) { return bundled }
        }
        let direct = home + "/is-gpt-nerfed/plugin/skills/is-gpt-nerfed/scripts/nerfed"
        if fm.fileExists(atPath: direct) { return direct }
        let cacheRoot = home + "/.codex/plugins/cache/is-gpt-nerfed/is-gpt-nerfed"
        if let versions = try? fm.contentsOfDirectory(atPath: cacheRoot) {
            for v in versions.sorted().reversed() {
                let p = cacheRoot + "/" + v + "/skills/is-gpt-nerfed/scripts/nerfed"
                if fm.fileExists(atPath: p) { return p }
            }
        }
        return nil
    }

    private static func environment() -> [String: String] {
        var env = ProcessInfo.processInfo.environment
        env["PATH"] = (env["PATH"] ?? "") + ":/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
        env.removeValue(forKey: "CODEX_SANDBOX_NETWORK_DISABLED")
        return env
    }

    /// Runs `dgc <args>` and returns stdout. Throws with stderr on a non-zero exit.
    static func run(_ args: [String], timeout: TimeInterval = 30) async throws -> String {
        guard let bin = locate() else { throw DGCError.notFound }
        let env = environment()
        return try await withCheckedThrowingContinuation { continuation in
            DispatchQueue.global(qos: .userInitiated).async {
                let process = Process()
                process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
                process.arguments = ["python3", bin] + args
                process.environment = env
                let out = Pipe(), err = Pipe()
                process.standardOutput = out
                process.standardError = err
                do {
                    try process.run()
                } catch {
                    continuation.resume(throwing: DGCError.failed(L10n.tr("cannot start python3: %@", error.localizedDescription)))
                    return
                }
                let watchdog = DispatchWorkItem { if process.isRunning { process.terminate() } }
                DispatchQueue.global().asyncAfter(deadline: .now() + timeout, execute: watchdog)
                let data = out.fileHandleForReading.readDataToEndOfFile()
                let errData = err.fileHandleForReading.readDataToEndOfFile()
                process.waitUntilExit()
                watchdog.cancel()
                if process.terminationStatus != 0 {
                    let msg = String(data: errData, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines)
                    continuation.resume(throwing: DGCError.failed(msg?.isEmpty == false ? msg! : L10n.tr("dgc exited with %@", String(process.terminationStatus))))
                } else {
                    continuation.resume(returning: String(data: data, encoding: .utf8) ?? "")
                }
            }
        }
    }

    /// Fire-and-forget (background probes); output goes to the plugin's worker log.
    static func spawnDetached(_ args: [String]) throws {
        guard let bin = locate() else { throw DGCError.notFound }
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        process.arguments = ["python3", bin] + args
        process.environment = environment()
        let logPath = home + "/.codex/is-gpt-nerfed/worker.log"
        if !FileManager.default.fileExists(atPath: logPath) {
            FileManager.default.createFile(atPath: logPath, contents: nil)
        }
        if let log = FileHandle(forWritingAtPath: logPath) {
            log.seekToEndOfFile()
            process.standardOutput = log
            process.standardError = log
        } else {
            process.standardOutput = FileHandle.nullDevice
            process.standardError = FileHandle.nullDevice
        }
        try process.run()
    }
}
