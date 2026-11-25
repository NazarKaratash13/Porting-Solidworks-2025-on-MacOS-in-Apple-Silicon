import CoreGraphics
import Foundation
import ImageIO
import UniformTypeIdentifiers

let canvas = 1024
let colorSpace = CGColorSpace(name: CGColorSpace.sRGB)!
let context = CGContext(data: nil, width: canvas, height: canvas, bitsPerComponent: 8,
                        bytesPerRow: 0, space: colorSpace,
                        bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!

func color(_ hex: UInt32, opacity: CGFloat = 1) -> CGColor {
    let r = CGFloat((hex >> 16) & 255) / 255
    let g = CGFloat((hex >> 8) & 255) / 255
    let b = CGFloat(hex & 255) / 255
    return CGColor(srgbRed: r, green: g, blue: b, alpha: opacity)
}

func gradient(_ colors: [CGColor], on shape: CGPath, from start: CGPoint, to end: CGPoint) {
    context.saveGState()
    context.addPath(shape)
    context.clip()
    let ramp = CGGradient(colorsSpace: colorSpace, colors: colors as CFArray, locations: nil)!
    context.drawLinearGradient(ramp, start: start, end: end,
                               options: [.drawsBeforeStartLocation, .drawsAfterEndLocation])
    context.restoreGState()
}

func polygon(_ points: [CGPoint]) -> CGPath {
    let shape = CGMutablePath()
    shape.addLines(between: points)
    shape.closeSubpath()
    return shape
}

func fill(_ shape: CGPath, with color: CGColor) {
    context.addPath(shape)
    context.setFillColor(color)
    context.fillPath()
}

func stroke(_ shape: CGPath, with color: CGColor, width: CGFloat) {
    context.addPath(shape)
    context.setStrokeColor(color)
    context.setLineWidth(width)
    context.setLineJoin(.round)
    context.strokePath()
}

let tile = CGRect(x: 91, y: 96, width: 842, height: 842)
let card = CGPath(roundedRect: tile, cornerWidth: 193, cornerHeight: 193, transform: nil)
context.saveGState()
context.setShadow(offset: CGSize(width: 0, height: -15), blur: 31, color: color(0x34080D, opacity: 0.43))
fill(card, with: color(0x8D1423))
context.restoreGState()
gradient([color(0x8C1129), color(0xD51D35), color(0xFF5A47)], on: card,
         from: CGPoint(x: 775, y: 104), to: CGPoint(x: 299, y: 940))
stroke(CGPath(roundedRect: tile.insetBy(dx: 2, dy: 2), cornerWidth: 191, cornerHeight: 191, transform: nil),
       with: color(0xFFE8D6, opacity: 0.26), width: 4)

func project(_ x: CGFloat, _ y: CGFloat, _ z: CGFloat = 0) -> CGPoint {
    CGPoint(x: 539 + x * 51 - y * 54, y: 327 + x * 27 + y * 29 + z)
}

let vertices: [(CGFloat, CGFloat)] = [(0, 0), (5.4, 0), (5.4, 2.2), (2.7, 2.2), (2.7, 5.5), (0, 5.5)]
let base = vertices.map { project($0.0, $0.1) }
let top = vertices.map { project($0.0, $0.1, 135) }
let topFace = polygon(top)

context.saveGState()
context.setShadow(offset: CGSize(width: 0, height: -17), blur: 36, color: color(0x4A0616, opacity: 0.68))
fill(polygon(base), with: color(0x8F1830))
context.restoreGState()

let light = CGPoint(x: 286, y: 675)
let shade = CGPoint(x: 760, y: 357)
for (index, dark, bright) in [(0, UInt32(0x495369), UInt32(0xA9B3CA)), (1, 0x475369, 0x949FB8),
                             (2, 0x616E89, 0xB4BFD3), (3, 0x7C89A1, 0xCED5E3), (5, 0x8490AA, 0xD9E4F3)] {
    let next = (index + 1) % base.count
    let face = polygon([base[index], base[next], top[next], top[index]])
    gradient([color(bright), color(dark)], on: face, from: light, to: shade)
    stroke(face, with: color(0x31364A, opacity: 0.30), width: 2)
}
gradient([color(0xFFFFFF), color(0xD1DBEF)], on: topFace, from: light, to: shade)
stroke(topFace, with: color(0xFFFFFF, opacity: 0.70), width: 3)

let center = project(1.33, 4.05, 135)
var projection = CGAffineTransform(a: 51, b: 27, c: -54, d: 29, tx: center.x, ty: center.y)
let hole = CGPath(ellipseIn: CGRect(x: -0.87, y: -0.87, width: 1.74, height: 1.74), transform: &projection)
gradient([color(0x321E33), color(0x802C48), color(0xC0445C)], on: hole,
         from: CGPoint(x: center.x, y: center.y + 32), to: CGPoint(x: center.x, y: center.y - 31))
stroke(hole, with: color(0x596176), width: 3)

guard CommandLine.arguments.count == 2,
      let output = CGImageDestinationCreateWithURL(URL(fileURLWithPath: CommandLine.arguments[1]) as CFURL,
                                                   UTType.png.identifier as CFString, 1, nil),
      let image = context.makeImage() else {
    fputs("Usage: Icon output.png\n", stderr)
    exit(2)
}
CGImageDestinationAddImage(output, image, nil)
guard CGImageDestinationFinalize(output) else { exit(1) }
