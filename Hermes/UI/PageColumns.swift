// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import SwiftUI

/// A page's widgets in two columns when the page is wide, as on the inner
/// display of iPhone Duo: the first widget across both, each other one in the
/// shorter column, the gap clear of the fold. One column below that width, as
/// the agent drew it.
enum PageColumns {
    static let from: CGFloat = 600

    static func view(_ view: JSONValue, width: CGFloat, fold: CGFloat) -> JSONValue {
        guard width >= from, var object = view.object, let widgets = object["VStack"]?.array, widgets.count > 2 else { return view }
        object["VStack"] = nil
        object["Masonry"] = .array(widgets)
        object["hSpacing"] = .number(Double(max(16, fold + 16)))
        return .object(object)
    }

    /// Whether a page this wide is on a narrow display, whose width the
    /// agent's twin checks: a wide one only gives widgets more room. No phone
    /// is narrower than 320, and the widths a display passes through as
    /// iPhone Duo opens or closes are narrower still.
    static func narrow(_ width: CGFloat) -> Bool {
        width >= 320 && width < from
    }
}

/// Places its first subview across the width and the others in two columns,
/// each in the one that ends higher.
struct MasonryLayout: Layout {
    var spacing: CGFloat
    var gap: CGFloat

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let width = proposal.width ?? PageColumns.from
        return CGSize(width: width, height: arrange(width, subviews).height)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        for (subview, frame) in zip(subviews, arrange(bounds.width, subviews).frames) {
            subview.place(at: CGPoint(x: bounds.minX + frame.minX, y: bounds.minY + frame.minY),
                          proposal: ProposedViewSize(width: frame.width, height: frame.height))
        }
    }

    private func arrange(_ width: CGFloat, _ subviews: Subviews) -> (frames: [CGRect], height: CGFloat) {
        let column = max(0, (width - gap) / 2)
        var ends: [CGFloat] = [0, 0]
        var frames: [CGRect] = []
        for (index, subview) in subviews.enumerated() {
            let across = index == 0
            let height = subview.sizeThatFits(ProposedViewSize(width: across ? width : column, height: nil)).height
            let side = ends[0] <= ends[1] ? 0 : 1
            let top = across ? 0 : ends[side]
            frames.append(CGRect(x: across || side == 0 ? 0 : column + gap, y: top, width: across ? width : column, height: height))
            guard height > 0 else { continue }
            if across {
                ends = [height + spacing, height + spacing]
            } else {
                ends[side] = top + height + spacing
            }
        }
        return (frames, max(0, ends.max()! - spacing))
    }
}
