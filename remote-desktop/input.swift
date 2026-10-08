import Foundation
import CoreGraphics
import ApplicationServices

func status() -> [String: Any] {
    let bounds = CGDisplayBounds(CGMainDisplayID())
    return ["capture": CGPreflightScreenCaptureAccess(), "control": CGPreflightPostEventAccess(), "accessibility": AXIsProcessTrusted(), "width": bounds.width, "height": bounds.height]
}
if CommandLine.arguments.contains("--status") {
    let data = try JSONSerialization.data(withJSONObject: status(), options: [.sortedKeys])
    print(String(data: data, encoding: .utf8)!)
    exit(0)
}
let codes: [String: CGKeyCode] = ["KeyA":0,"KeyS":1,"KeyD":2,"KeyF":3,"KeyH":4,"KeyG":5,"KeyZ":6,"KeyX":7,"KeyC":8,"KeyV":9,"KeyB":11,"KeyQ":12,"KeyW":13,"KeyE":14,"KeyR":15,"KeyY":16,"KeyT":17,"Digit1":18,"Digit2":19,"Digit3":20,"Digit4":21,"Digit6":22,"Digit5":23,"Equal":24,"Digit9":25,"Digit7":26,"Minus":27,"Digit8":28,"Digit0":29,"BracketRight":30,"KeyO":31,"KeyU":32,"BracketLeft":33,"KeyI":34,"KeyP":35,"Enter":36,"KeyL":37,"KeyJ":38,"Quote":39,"KeyK":40,"Semicolon":41,"Backslash":42,"Comma":43,"Slash":44,"KeyN":45,"KeyM":46,"Period":47,"Tab":48,"Space":49,"Backquote":50,"Backspace":51,"Escape":53,"MetaRight":54,"MetaLeft":55,"ShiftLeft":56,"CapsLock":57,"AltLeft":58,"ControlLeft":59,"ShiftRight":60,"AltRight":61,"ControlRight":62,"F17":64,"NumpadDecimal":65,"NumpadMultiply":67,"NumpadAdd":69,"NumLock":71,"NumpadDivide":75,"NumpadEnter":76,"NumpadSubtract":78,"NumpadEqual":81,"Numpad0":82,"Numpad1":83,"Numpad2":84,"Numpad3":85,"Numpad4":86,"Numpad5":87,"Numpad6":88,"Numpad7":89,"Numpad8":91,"Numpad9":92,"F5":96,"F6":97,"F7":98,"F3":99,"F8":100,"F9":101,"F11":103,"F13":105,"F16":106,"F14":107,"F10":109,"F12":111,"F15":113,"Help":114,"Home":115,"PageUp":116,"Delete":117,"F4":118,"End":119,"F2":120,"PageDown":121,"F1":122,"ArrowLeft":123,"ArrowRight":124,"ArrowDown":125,"ArrowUp":126]
while let line = readLine() {
    do {
        guard let bytes = line.data(using: .utf8), let command = try JSONSerialization.jsonObject(with: bytes) as? [String: Any], let type = command["type"] as? String else { throw NSError(domain:"input",code:1) }
        guard CGPreflightPostEventAccess() else { throw NSError(domain:"permission",code:1) }
        if type == "text" {
            let chars = Array((command["text"] as? String ?? "").utf16)
            guard chars.count <= 4096 else { throw NSError(domain:"input",code:2) }
            for offset in stride(from: 0, to: chars.count, by: 128) {
                let chunk = Array(chars[offset..<min(offset+128,chars.count)])
                chunk.withUnsafeBufferPointer { buffer in
                    for down in [true, false] {
                        let event = CGEvent(keyboardEventSource: nil, virtualKey: 0, keyDown: down)!
                        event.keyboardSetUnicodeString(stringLength: buffer.count, unicodeString: buffer.baseAddress!)
                        event.post(tap: .cghidEventTap)
                    }
                }
            }
        } else if type == "key" || type == "tap" {
            guard let code = command["code"] as? String, let key = codes[code] else { throw NSError(domain:"input",code:3) }
            let event = CGEvent(keyboardEventSource: nil, virtualKey: key, keyDown: command["down"] as? Bool ?? false)!
            var flags: CGEventFlags = []
            if command["shift"] as? Bool == true { flags.insert(.maskShift) }
            if command["ctrl"] as? Bool == true { flags.insert(.maskControl) }
            if command["alt"] as? Bool == true { flags.insert(.maskAlternate) }
            if command["meta"] as? Bool == true { flags.insert(.maskCommand) }
            event.flags = flags
            if type == "tap" {
                let down = CGEvent(keyboardEventSource:nil, virtualKey:key, keyDown:true)!
                down.flags = flags
                down.post(tap:.cghidEventTap)
                usleep(25000)
                CGEvent(keyboardEventSource:nil,virtualKey:key,keyDown:false)?.post(tap:.cghidEventTap)
            } else { event.post(tap: .cghidEventTap) }
        } else if type == "scroll" {
            let dx = max(-1000,min(1000,command["dx"] as? Int ?? 0))
            let dy = max(-1000,min(1000,command["dy"] as? Int ?? 0))
            CGEvent(scrollWheelEvent2Source:nil,units:.pixel,wheelCount:2,wheel1:Int32(-dy),wheel2:Int32(-dx),wheel3:0)?.post(tap:.cghidEventTap)
        } else if type == "mouse" {
            let bounds = CGDisplayBounds(CGMainDisplayID())
            let x = max(0,min(1,command["x"] as? Double ?? 0))
            let y = max(0,min(1,command["y"] as? Double ?? 0))
            let point = CGPoint(x:bounds.minX+x*(bounds.width-1),y:bounds.minY+y*(bounds.height-1))
            let right = command["button"] as? Int == 2
            let button: CGMouseButton = right ? .right : .left
            let action = command["action"] as? String ?? "move"
            if action == "click" {
                let clicks = Int64(max(1,min(2,command["clicks"] as? Int ?? 1)))
                for kind in [right ? CGEventType.rightMouseDown : .leftMouseDown,right ? CGEventType.rightMouseUp : .leftMouseUp] {
                    let click = CGEvent(mouseEventSource:nil,mouseType:kind,mouseCursorPosition:point,mouseButton:button)!
                    click.setIntegerValueField(.mouseEventClickState,value:clicks)
                    click.post(tap:.cghidEventTap)
                    usleep(25000)
                }
                print("{\"ok\":true}")
                fflush(stdout)
                continue
            }
            let kind: CGEventType = action == "down" ? (right ? .rightMouseDown : .leftMouseDown) : action == "up" ? (right ? .rightMouseUp : .leftMouseUp) : command["drag"] as? Bool == true ? (right ? .rightMouseDragged : .leftMouseDragged) : .mouseMoved
            let event = CGEvent(mouseEventSource:nil,mouseType:kind,mouseCursorPosition:point,mouseButton:button)!
            event.setIntegerValueField(.mouseEventClickState,value:Int64(max(1,min(2,command["clicks"] as? Int ?? 1))))
            event.post(tap:.cghidEventTap)
        } else { throw NSError(domain:"input",code:4) }
        print("{\"ok\":true}")
    } catch { print("{\"ok\":false}") }
    fflush(stdout)
}
