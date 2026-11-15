// swift-tools-version: 5.10
import PackageDescription

// A tiny command line program that keeps Argmax's on-device speech models
// loaded and answers requests from Beacon's Python server.
//   WhisperKit -> speech to text
//   TTSKit     -> text to speech
let package = Package(
    name: "argmax-bridge",
    platforms: [.macOS(.v14)],
    dependencies: [
        .package(url: "https://github.com/argmaxinc/argmax-oss-swift.git", exact: "1.1.1"),
    ],
    targets: [
        .executableTarget(
            name: "argmax-bridge",
            dependencies: [
                .product(name: "WhisperKit", package: "argmax-oss-swift"),
                .product(name: "TTSKit", package: "argmax-oss-swift"),
            ]
        ),
    ]
)
