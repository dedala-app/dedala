// SPDX-FileCopyrightText: 2026 Julien Malka
// SPDX-License-Identifier: AGPL-3.0-or-later

import MapKit
import SwiftUI

struct MapSpec: ViewSpec {
    let places: Dynamic
    let style: String?
    let interactive: Condition?
    let distance: Dynamic?

    init(_ reader: inout Reader) {
        places = reader.mainValue()
        style = reader.word("style")
        interactive = reader.condition("interactive")
        distance = reader.value("distance")
    }

    func view(_ scope: Scope, _ element: Element) -> AnyView {
        let resolved = places.resolve(scope)
        let markers = (resolved["markers"]?.array ?? []).enumerated().compactMap { index, marker -> MapMarkerSpec? in
            guard let lat = marker["lat"]?.number, let lon = marker["lon"]?.number else {
                scope.context.report("A map marker needs lat and lon")
                return nil
            }
            return MapMarkerSpec(
                id: index,
                title: marker["title"]?.text ?? "",
                symbol: marker["symbol"]?.string,
                color: Tokens.color(marker["color"]) ?? .red,
                coordinate: CLLocationCoordinate2D(latitude: lat, longitude: lon)
            )
        }
        let route = (resolved["route"]?.array ?? []).compactMap { point -> CLLocationCoordinate2D? in
            guard let pair = point.array, pair.count == 2, let lat = pair[0].number, let lon = pair[1].number else { return nil }
            return CLLocationCoordinate2D(latitude: lat, longitude: lon)
        }
        let view = MapNodeView(
            markers: markers,
            route: route,
            style: style,
            interactive: interactive?.holds(scope) == true,
            distance: resolved["distance"]?.number ?? scope.number(distance)
        )
        .frame(height: element.facts.hasHeight ? nil : 180)
        if !element.facts.clips {
            return AnyView(view.clipShape(.rect(cornerRadius: 16, style: .continuous)))
        }
        return AnyView(view)
    }
}

struct MapMarkerSpec: Identifiable {
    let id: Int
    let title: String
    let symbol: String?
    let color: Color
    let coordinate: CLLocationCoordinate2D
}

struct MapNodeView: View {
    let markers: [MapMarkerSpec]
    let route: [CLLocationCoordinate2D]
    let style: String?
    let interactive: Bool
    let distance: Double?

    /// One place, or a camera height asked for, gets a camera at that height
    /// (1.5km by default); several places are framed together.
    private var position: MapCameraPosition {
        let points = markers.map(\.coordinate) + route
        guard !points.isEmpty, distance != nil || points.count == 1 else { return .automatic }
        let center = CLLocationCoordinate2D(
            latitude: points.map(\.latitude).reduce(0, +) / Double(points.count),
            longitude: points.map(\.longitude).reduce(0, +) / Double(points.count)
        )
        return .camera(MapCamera(centerCoordinate: center, distance: distance ?? 1_500))
    }

    var body: some View {
        Map(initialPosition: position, interactionModes: interactive ? .all : []) {
            ForEach(markers) { marker in
                if let symbol = marker.symbol {
                    Marker(marker.title, systemImage: symbol, coordinate: marker.coordinate)
                        .tint(marker.color)
                } else {
                    Marker(marker.title, coordinate: marker.coordinate)
                        .tint(marker.color)
                }
            }
            if route.count > 1 {
                MapPolyline(coordinates: route)
                    .stroke(.blue, lineWidth: 5)
            }
        }
        .mapStyle(mapStyle)
        .id(markers.map { "\($0.coordinate.latitude),\($0.coordinate.longitude)" }.joined() + "\(route.count)-\(distance ?? 0)")
    }

    private var mapStyle: MapStyle {
        switch style {
        case "imagery": .imagery(elevation: .realistic)
        case "hybrid": .hybrid(elevation: .realistic)
        default: .standard(elevation: .realistic)
        }
    }
}
