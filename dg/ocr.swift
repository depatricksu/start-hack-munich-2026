// Text in a photo / scanned page with macOS Vision. Owner: Riky.
//   ocr_bin <file>      one file, print its text, exit
//   ocr_bin --serve     stay alive: read one file path per line on stdin, print its text, then "<<<OCR-END>>>"
//                       (Vision loads its model once, so every page after the first is fast)
import Vision
import AppKit
import Foundation

func ocr(_ path: String) -> String {
    let url = URL(fileURLWithPath: path)
    guard let img = NSImage(contentsOf: url),
          let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else { return "" }
    let req = VNRecognizeTextRequest()
    req.recognitionLevel = .accurate
    req.usesLanguageCorrection = false
    do { try VNImageRequestHandler(cgImage: cg, options: [:]).perform([req]) } catch { return "" }
    return (req.results ?? []).compactMap { $0.topCandidates(1).first?.string }.joined(separator: "\n")
}

setvbuf(stdout, nil, _IONBF, 0)
let args = CommandLine.arguments
if args.count > 1 && args[1] == "--serve" {
    while let line = readLine() {
        let path = line.trimmingCharacters(in: .whitespacesAndNewlines)
        if !path.isEmpty { print(ocr(path)) }
        print("<<<OCR-END>>>")
        fflush(stdout)
    }
} else if args.count > 1 {
    print(ocr(args[1]))
}
