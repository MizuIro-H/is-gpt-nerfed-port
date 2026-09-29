// Prints window ids and bounds of a running app plus the main display size. Used by tools/screenshot.sh.
import CoreGraphics
import Foundation

let owner = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "IsGPTNerfed"
let bounds = CGDisplayBounds(CGMainDisplayID())
print("display \(Int(bounds.width))x\(Int(bounds.height))")
let list = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]] ?? []
for w in list where (w[kCGWindowOwnerName as String] as? String) == owner {
    let id = w[kCGWindowNumber as String] as? Int ?? 0
    let name = w[kCGWindowName as String] as? String ?? ""
    let b = w[kCGWindowBounds as String] as? [String: Any] ?? [:]
    let layer = w[kCGWindowLayer as String] as? Int ?? 0
    print("window \(id) layer=\(layer) name=\(name) bounds=\(b["X"] ?? 0),\(b["Y"] ?? 0),\(b["Width"] ?? 0),\(b["Height"] ?? 0)")
}
