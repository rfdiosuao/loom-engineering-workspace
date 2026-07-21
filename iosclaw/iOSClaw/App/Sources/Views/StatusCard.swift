import SwiftUI

struct StatusCard: View {
    enum Tone {
        case ok
        case warn
        case neutral

        var color: Color {
            switch self {
            case .ok: return Color(red: 0.34, green: 0.85, blue: 0.73)
            case .warn: return Color.orange
            case .neutral: return Color(red: 0.55, green: 0.67, blue: 0.86)
            }
        }
    }

    let title: String
    let value: String
    let detail: String
    let tone: Tone

    var body: some View {
        HStack(alignment: .top, spacing: 14) {
            Circle()
                .fill(tone.color)
                .frame(width: 12, height: 12)
                .padding(.top, 6)
            VStack(alignment: .leading, spacing: 4) {
                Text(title)
                    .font(.caption.weight(.bold))
                    .textCase(.uppercase)
                    .foregroundStyle(.white.opacity(0.56))
                Text(value)
                    .font(.title3.weight(.bold))
                    .foregroundStyle(.white)
                Text(detail)
                    .font(.footnote)
                    .foregroundStyle(.white.opacity(0.68))
                    .textSelection(.enabled)
            }
            Spacer(minLength: 0)
        }
        .padding(16)
        .background(Color.white.opacity(0.08))
        .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
    }
}
