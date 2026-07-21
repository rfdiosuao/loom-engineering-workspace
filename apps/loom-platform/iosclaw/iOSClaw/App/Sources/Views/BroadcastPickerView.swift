import SwiftUI
import ReplayKit

struct BroadcastPickerView: UIViewRepresentable {
    let preferredExtension: String

    func makeUIView(context: Context) -> RPSystemBroadcastPickerView {
        let view = RPSystemBroadcastPickerView(frame: .zero)
        view.preferredExtension = preferredExtension
        view.showsMicrophoneButton = false
        if let button = view.subviews.compactMap({ $0 as? UIButton }).first {
            button.tintColor = .white
            button.imageView?.contentMode = .scaleAspectFit
        }
        return view
    }

    func updateUIView(_ uiView: RPSystemBroadcastPickerView, context: Context) {
        uiView.preferredExtension = preferredExtension
    }
}
