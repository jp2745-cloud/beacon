import Foundation
import TTSKit
import WhisperKit

// Beacon <-> Argmax bridge.
//
// Protocol: Beacon writes one JSON object per line to stdin. Every reply is a
// single line on stdout that starts with "@@BEACON " followed by JSON, so any
// logging printed by the libraries can be ignored by the reader.
//
//   {"id": 1, "cmd": "transcribe", "path": "/tmp/in.wav"}
//   {"id": 2, "cmd": "speak", "text": "Press hard on the wound.", "out": "/tmp/out.wav"}

func emit(_ object: [String: Any]) {
    guard let data = try? JSONSerialization.data(withJSONObject: object, options: []),
          let json = String(data: data, encoding: .utf8),
          let line = ("@@BEACON " + json + "\n").data(using: .utf8)
    else { return }
    FileHandle.standardOutput.write(line)   // unbuffered, unlike print() into a pipe
}

func elapsedMs(since start: Date) -> Int {
    return Int(Date().timeIntervalSince(start) * 1000)
}

@main
struct Bridge {
    static func main() async {
        var whisperModel = "small.en"
        var ttsModelName = "0.6b"
        var voiceName = "serena"

        var args = Array(CommandLine.arguments.dropFirst())
        while args.count >= 2 {
            let key = args.removeFirst()
            let value = args.removeFirst()
            switch key {
            case "--whisper": whisperModel = value
            case "--tts": ttsModelName = value
            case "--voice": voiceName = value
            default: break
            }
        }

        let speaker: Qwen3Speaker = Qwen3Speaker(rawValue: voiceName) ?? Qwen3Speaker.serena
        let ttsVariant: TTSModelVariant = TTSModelVariant(rawValue: ttsModelName) ?? TTSModelVariant.qwen3TTS_0_6b

        // Speech to text is required. If it cannot load there is nothing to do.
        let whisper: WhisperKit
        do {
            emit(["event": "status", "message": "Loading WhisperKit \(whisperModel). The first run downloads it."])
            whisper = try await WhisperKit(WhisperKitConfig(model: whisperModel, verbose: false))
        } catch {
            emit(["event": "fatal", "message": "WhisperKit failed to load: \(error)"])
            exit(1)
        }

        // Text to speech is optional: TTSKit needs macOS 15. If it cannot load,
        // Beacon keeps Argmax for listening and uses the system voice for speaking.
        var tts: TTSKit? = nil
        var ttsNote = ""
        if ttsModelName != "none" {
            do {
                emit(["event": "status", "message": "Loading TTSKit \(ttsModelName). The first run downloads about 1 GB."])
                let loaded = try await TTSKit(TTSKitConfig(model: ttsVariant, verbose: false))
                // Say one word now so the first real sentence does not pay the warm-up cost.
                emit(["event": "status", "message": "Warming up the voice"])
                _ = try await loaded.generate(text: "Ready.", speaker: speaker, language: Qwen3Language.english)
                tts = loaded
            } catch {
                ttsNote = "TTSKit failed to load: \(error)"
            }
        }

        emit([
            "event": "ready",
            "whisper": whisperModel,
            "tts": tts == nil ? "" : ttsModelName,
            "voice": speaker.rawValue,
            "note": ttsNote,
        ])

        let decoding = DecodingOptions(language: "en", skipSpecialTokens: true, withoutTimestamps: true)

        while let line = readLine(strippingNewline: true) {
            guard let data = line.data(using: .utf8),
                  let parsed = try? JSONSerialization.jsonObject(with: data, options: []),
                  let request = parsed as? [String: Any],
                  let id = request["id"] as? Int,
                  let command = request["cmd"] as? String
            else { continue }

            let started = Date()
            do {
                switch command {
                case "transcribe":
                    let path = (request["path"] as? String) ?? ""
                    let results: [TranscriptionResult] = try await whisper.transcribe(audioPath: path, decodeOptions: decoding)
                    let text = results.map { $0.text }.joined(separator: " ")
                    emit(["id": id, "ok": true, "text": text, "ms": elapsedMs(since: started)])

                case "speak":
                    let text = (request["text"] as? String) ?? ""
                    let outPath = (request["out"] as? String) ?? (NSTemporaryDirectory() + "beacon-out.wav")
                    let outURL = URL(fileURLWithPath: outPath)
                    guard let voice = tts else {
                        emit(["id": id, "ok": false, "error": "TTSKit is not loaded"])
                        continue
                    }
                    let result: SpeechResult = try await voice.generate(text: text, speaker: speaker, language: Qwen3Language.english)
                    let saved: URL = try await AudioOutput.saveAudio(
                        result.audio,
                        toFolder: outURL.deletingLastPathComponent(),
                        filename: outURL.lastPathComponent,
                        sampleRate: result.sampleRate,
                        format: AudioOutput.AudioFileFormat.wav
                    )
                    emit(["id": id, "ok": true, "path": saved.path, "ms": elapsedMs(since: started), "seconds": result.audioDuration])

                case "ping":
                    emit(["id": id, "ok": true])

                default:
                    emit(["id": id, "ok": false, "error": "unknown command \(command)"])
                }
            } catch {
                emit(["id": id, "ok": false, "error": "\(error)"])
            }
        }
    }
}
