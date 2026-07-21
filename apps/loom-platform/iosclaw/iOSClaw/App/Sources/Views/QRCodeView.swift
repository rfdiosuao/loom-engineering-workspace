import SwiftUI
import CoreImage.CIFilterBuiltins
import UIKit

struct QRCodeView: View {
    let text: String
    private let context = CIContext()
    private let filter = CIFilter.qrCodeGenerator()

    var body: some View {
        Image(uiImage: makeQRCode())
            .interpolation(.none)
            .resizable()
            .scaledToFit()
            .padding(12)
            .accessibilityLabel("iOSClaw pairing QR code")
    }

    private func makeQRCode() -> UIImage {
        filter.setValue(Data(text.utf8), forKey: "inputMessage")
        filter.correctionLevel = "M"
        guard
            let output = filter.outputImage,
            let image = context.createCGImage(output.transformed(by: CGAffineTransform(scaleX: 8, y: 8)), from: output.extent)
        else {
            return UIImage(systemName: "qrcode") ?? UIImage()
        }
        return UIImage(cgImage: image)
    }
}
