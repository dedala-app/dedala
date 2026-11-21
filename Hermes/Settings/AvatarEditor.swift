// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import SwiftUI

/// Making the agent's face, as in the Memoji editor: the face alive at the
/// top with its name under it, one part at a time below, each choice shown on
/// the face itself; or a picture instead. Every choice is written at once to
/// the store `profile`, which the agent writes too.
struct AvatarEditor: View {
    @Environment(Agent.self) private var agent
    @Environment(Hub.self) private var hub
    @State private var look: AvatarLook?
    @State private var part = Part.skin
    @State private var name = ""
    @FocusState private var naming: Bool

    enum Part: String, CaseIterable, Identifiable {
        case skin = "Skin", hair = "Hair", beard = "Beard", glasses = "Glasses", clothes = "Clothes"
        var id: Self { self }
    }

    var body: some View {
        let look = self.look ?? agent.look ?? AvatarLook.derived(from: agent.name)
        VStack(spacing: 0) {
            Group {
                if self.look == nil, let picture = agent.picture {
                    Image(uiImage: picture).resizable().scaledToFill()
                } else {
                    AvataaarFace(look: look)
                }
            }
            .frame(width: 160, height: 160)
            .background(PosterWash().clipShape(.circle))
            .clipShape(.circle)
            .padding(.top, 12)
            TextField("Name", text: $name)
                .font(.title2.weight(.semibold))
                .multilineTextAlignment(.center)
                .textInputAutocapitalization(.words)
                .autocorrectionDisabled()
                .submitLabel(.done)
                .focused($naming)
                .onSubmit(rename)
                .onChange(of: naming) { if !naming { rename() } }
                .padding(.horizontal, 32)
                .padding(.vertical, 12)
            Picker("Part", selection: $part) {
                ForEach(Part.allCases) { Text($0.rawValue).tag($0) }
            }
            .pickerStyle(.segmented)
            .padding(.horizontal, 16)
            .padding(.bottom, 8)
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    choices(for: part, look)
                }
                .padding(16)
            }
        }
        .navigationTitle("Name and face")
        .navigationBarTitleDisplayMode(.inline)
        .onAppear { name = agent.name }
        .onDisappear(perform: rename)
        .toolbar {
            ToolbarItemGroup(placement: .topBarTrailing) {
                Button("Shuffle", systemImage: "dice") { pick(AvatarLook.random()) }
                Menu("Picture", systemImage: "photo") {
                    Button("Choose Photo", systemImage: "photo.on.rectangle") { choosePicture("library") }
                    if UIImagePickerController.isSourceTypeAvailable(.camera) {
                        Button("Take Photo", systemImage: "camera") { choosePicture("camera") }
                    }
                    if agent.picture != nil {
                        Button("Remove Picture", systemImage: "trash", role: .destructive) {
                            pick(agent.look ?? AvatarLook.derived(from: agent.name))
                        }
                    }
                }
            }
        }
    }

    @ViewBuilder private func choices(for part: Part, _ look: AvatarLook) -> some View {
        switch part {
        case .skin:
            faces(AvatarLook.skins, look) { $0.skin = $1 }
        case .hair:
            if let top = look.top, AvatarLook.headwear.contains(top) {
                swatches("Color", AvatarLook.fabrics, selected: look.hatColor) { var next = look; next.hatColor = $0; pick(next) }
            } else if look.top != nil {
                swatches("Color", AvatarLook.hairColors, selected: look.hairColor) { var next = look; next.hairColor = $0; pick(next) }
            }
            faces([nil] + AvatarLook.hairs, look) { $0.top = $1 }
        case .beard:
            if look.facialHair != nil {
                swatches("Color", AvatarLook.hairColors, selected: look.facialHairColor) { var next = look; next.facialHairColor = $0; pick(next) }
            }
            faces([nil] + AvatarLook.beards, look) { $0.facialHair = $1 }
        case .glasses:
            faces([nil] + AvatarLook.glasses, look) { $0.accessories = $1 }
        case .clothes:
            swatches("Color", AvatarLook.fabrics, selected: look.clothesColor) { var next = look; next.clothesColor = $0; pick(next) }
            faces(AvatarLook.clothes, look) { $0.clothing = $1 }
            if look.clothing == "graphicShirt" {
                faces(AvatarLook.graphics, look) { $0.clothingGraphic = $1 }
            }
        }
    }

    /// The face with each choice for one part, the current one ringed.
    private func faces<Value: Hashable>(_ values: [Value], _ look: AvatarLook, apply: @escaping (inout AvatarLook, Value) -> Void) -> some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 88), spacing: 12)], spacing: 12) {
            ForEach(values, id: \.self) { value in
                let variant = { var next = look; apply(&next, value); return next }()
                Button { pick(variant) } label: {
                    LookThumbnail(look: variant)
                        .overlay {
                            RoundedRectangle(cornerRadius: 18, style: .continuous)
                                .strokeBorder(Color.accentColor, lineWidth: variant == look ? 3 : 0)
                        }
                }
                .buttonStyle(.plain)
            }
        }
    }

    private func swatches(_ title: String, _ colors: [String], selected: String, pick: @escaping (String) -> Void) -> some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 10) {
                ForEach(colors, id: \.self) { color in
                    Button { pick(color) } label: {
                        Circle()
                            .fill(Tokens.color(.string("#\(color)")) ?? .gray)
                            .frame(width: 34, height: 34)
                            .overlay(Circle().strokeBorder(.separator, lineWidth: 1))
                            .padding(3)
                            .overlay(Circle().strokeBorder(Color.accentColor, lineWidth: color == selected ? 2.5 : 0))
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("\(title) \(color)")
                }
            }
            .padding(.vertical, 2)
        }
    }

    private func pick(_ next: AvatarLook) {
        withAnimation(.snappy) { look = next }
        write(["look": next.json, "picture": .null])
    }

    private func choosePicture(_ source: String) {
        Task {
            guard let picked = await PhotoPicking.pick(source) else { return }
            look = nil
            write(["picture": picked.merging(.object(["name": .string("picture-\(Int(Date.now.timeIntervalSince1970)).jpg")]))])
        }
    }

    private func rename() {
        let given = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !given.isEmpty, given != agent.name else { return }
        write(["name": .string(given)])
    }

    private func write(_ fields: [String: JSONValue]) {
        try? hub.edit(.object(fields.merging(["store": .string(Hub.profile)]) { $1 }), from: Hub.profile)
    }
}

/// One choice in the editor: the face with it, at rest.
private struct LookThumbnail: View {
    let look: AvatarLook
    @Environment(\.displayScale) private var scale
    @State private var image: UIImage?

    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .fill(Color(.secondarySystemBackground))
            if let image {
                Image(uiImage: image)
                    .resizable()
                    .scaledToFit()
                    .padding(4)
                    .transition(.opacity)
            }
        }
        .aspectRatio(1, contentMode: .fit)
        .task(id: look) {
            let drawn = await Avataaar.face(look, size: 88, scale: scale)
            withAnimation(.easeOut(duration: 0.15)) { image = drawn }
        }
    }
}
