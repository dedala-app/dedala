// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import PhotosUI
import UIKit
import UniformTypeIdentifiers

/// A photo taken or picked for a `Photo` input: saved as a JPEG the page can
/// show and an edit can carry, under the app's `outbound` folder until the
/// edit is acknowledged. Photos for a message are picked here too.
@MainActor
enum PhotoPicking {
    static let longestSide: CGFloat = 1600

    static var folder: URL {
        let base = (try? FileManager.default.url(for: .applicationSupportDirectory, in: .userDomainMask, appropriateFor: nil, create: true)) ?? URL.temporaryDirectory
        return base.appending(path: "outbound", directoryHint: .isDirectory)
    }

    /// `camera` or `library`; the picture as the state holds it, nil when none was chosen.
    static func pick(_ source: String) async -> JSONValue? {
        guard let presenter = UIApplication.shared.connectedScenes.compactMap({ ($0 as? UIWindowScene)?.keyWindow?.rootViewController }).first else { return nil }
        let image: UIImage? = source == "camera" ? await camera(from: presenter.top) : await libraryImage(from: presenter.top)
        guard let image else { return nil }
        return keep(image)
    }

    /// `camera` or `library`, up to `limit` from the library, in the order you
    /// picked them: each picture as it was taken, in its own format.
    static func pictures(_ source: String, limit: Int) async -> [Data] {
        guard let presenter = UIApplication.shared.connectedScenes.compactMap({ ($0 as? UIWindowScene)?.keyWindow?.rootViewController }).first else { return [] }
        if source == "camera" {
            return await camera(from: presenter.top).flatMap { $0.jpegData(compressionQuality: 0.9) }.map { [$0] } ?? []
        }
        var found: [Data] = []
        for provider in await library(from: presenter.top, limit: limit) {
            if let data = await data(of: provider) { found.append(data) }
        }
        return found
    }

    /// The picture as the state holds it: `{local, name, size, type}`.
    static func keep(_ image: UIImage, name: String = "photo.jpg") -> JSONValue? {
        let scale = min(1, longestSide / max(image.size.width, image.size.height, 1))
        let sized = scale < 1 ? image.preparingThumbnail(of: CGSize(width: image.size.width * scale, height: image.size.height * scale)) ?? image : image
        guard let data = sized.jpegData(compressionQuality: 0.85) else { return nil }
        try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let url = folder.appending(path: "\(UUID().uuidString).jpg")
        guard (try? data.write(to: url, options: .atomic)) != nil else { return nil }
        return .object(["local": .string(url.path), "name": .string(name), "size": .number(Double(data.count)), "type": "image/jpeg"])
    }

    private static func camera(from presenter: UIViewController) async -> UIImage? {
        guard UIImagePickerController.isSourceTypeAvailable(.camera) else { return nil }
        return await withCheckedContinuation { continuation in
            let picker = UIImagePickerController()
            picker.sourceType = .camera
            let delegate = CameraDelegate { image in continuation.resume(returning: image) }
            picker.delegate = delegate
            objc_setAssociatedObject(picker, &CameraDelegate.key, delegate, .OBJC_ASSOCIATION_RETAIN)
            presenter.present(picker, animated: true)
        }
    }

    private static func library(from presenter: UIViewController, limit: Int) async -> [NSItemProvider] {
        var configuration = PHPickerConfiguration()
        configuration.filter = .images
        configuration.selectionLimit = limit
        configuration.selection = .ordered
        return await withCheckedContinuation { continuation in
            let picker = PHPickerViewController(configuration: configuration)
            let delegate = LibraryDelegate { providers in continuation.resume(returning: providers) }
            picker.delegate = delegate
            objc_setAssociatedObject(picker, &LibraryDelegate.key, delegate, .OBJC_ASSOCIATION_RETAIN)
            presenter.present(picker, animated: true)
        }
    }

    private static func libraryImage(from presenter: UIViewController) async -> UIImage? {
        guard let provider = await library(from: presenter, limit: 1).first, provider.canLoadObject(ofClass: UIImage.self) else { return nil }
        return await withCheckedContinuation { continuation in
            provider.loadObject(ofClass: UIImage.self) { object, _ in continuation.resume(returning: object as? UIImage) }
        }
    }

    private static func data(of provider: NSItemProvider) async -> Data? {
        await withCheckedContinuation { continuation in
            _ = provider.loadDataRepresentation(forTypeIdentifier: UTType.image.identifier) { data, _ in continuation.resume(returning: data) }
        }
    }
}

private extension UIViewController {
    var top: UIViewController {
        presentedViewController?.top ?? self
    }
}

private final class CameraDelegate: NSObject, UIImagePickerControllerDelegate, UINavigationControllerDelegate {
    static var key = 0
    private var done: ((UIImage?) -> Void)?

    init(done: @escaping (UIImage?) -> Void) { self.done = done }

    func imagePickerController(_ picker: UIImagePickerController, didFinishPickingMediaWithInfo info: [UIImagePickerController.InfoKey: Any]) {
        picker.dismiss(animated: true)
        done?(info[.originalImage] as? UIImage)
        done = nil
    }

    func imagePickerControllerDidCancel(_ picker: UIImagePickerController) {
        picker.dismiss(animated: true)
        done?(nil)
        done = nil
    }
}

private final class LibraryDelegate: NSObject, PHPickerViewControllerDelegate {
    static var key = 0
    private var done: (([NSItemProvider]) -> Void)?

    init(done: @escaping ([NSItemProvider]) -> Void) { self.done = done }

    func picker(_ picker: PHPickerViewController, didFinishPicking results: [PHPickerResult]) {
        picker.dismiss(animated: true)
        done?(results.map(\.itemProvider))
        done = nil
    }
}
