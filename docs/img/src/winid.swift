import CoreGraphics
let opts = CGWindowListOption(arrayLiteral: .optionOnScreenOnly)
for w in (CGWindowListCopyWindowInfo(opts, kCGNullWindowID) as! [[String: Any]]) {
  let owner = w["kCGWindowOwnerName"] as? String ?? ""
  if owner.lowercased().contains("agterm") {
    print(w["kCGWindowNumber"]!, w["kCGWindowName"] ?? "", w["kCGWindowBounds"] ?? "")
  }
}
