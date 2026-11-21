// A voice message -> text, with the Mac's own speech recognition (Speech framework). Used by dg/attach.py.
//   stt_bin <audio file> [locale, default en-US]     prints the transcript, exit 0
// Exit codes: 2 speech recognition not allowed for this app, 3 recognition error, 4 no recognizer, 5 timeout.
// Built with an embedded Info.plist (dg/stt.plist): without NSSpeechRecognitionUsageDescription macOS kills the tool.
import Speech
import Foundation

let args = CommandLine.arguments
guard args.count > 1 else { print("usage: stt_bin <audio file> [locale]"); exit(64) }
let url = URL(fileURLWithPath: args[1])
let locale = Locale(identifier: args.count > 2 ? args[2] : "en-US")

SFSpeechRecognizer.requestAuthorization { status in
    guard status == .authorized else { print("AUTH_DENIED", status.rawValue); exit(2) }
    guard let rec = SFSpeechRecognizer(locale: locale), rec.isAvailable else { print("NO_RECOGNIZER"); exit(4) }
    let req = SFSpeechURLRecognitionRequest(url: url)
    req.shouldReportPartialResults = false
    rec.recognitionTask(with: req) { result, error in
        if let r = result, r.isFinal { print(r.bestTranscription.formattedString); exit(0) }
        if let e = error { print("ERR", e.localizedDescription); exit(3) }
    }
}
RunLoop.main.run(until: Date().addingTimeInterval(60))
print("TIMEOUT"); exit(5)
