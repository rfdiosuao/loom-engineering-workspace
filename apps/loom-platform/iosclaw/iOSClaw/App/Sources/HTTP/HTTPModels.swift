import Foundation

struct HTTPRequest {
    let method: String
    let path: String
    let query: String
    let version: String
    let headers: [String: String]
    let body: Data

    var pathWithQuery: String {
        query.isEmpty ? path : "\(path)?\(query)"
    }

    func header(_ name: String) -> String? {
        headers[name.lowercased()]
    }

    var jsonBody: [String: Any] {
        guard !body.isEmpty else { return [:] }
        return (try? JSONSerialization.jsonObject(with: body)) as? [String: Any] ?? [:]
    }

    static func parseIfComplete(_ data: Data) -> HTTPRequest? {
        guard let headerRange = data.range(of: Data("\r\n\r\n".utf8)) else { return nil }
        let headerData = data.subdata(in: data.startIndex..<headerRange.lowerBound)
        guard let headerText = String(data: headerData, encoding: .utf8) else { return nil }

        let lines = headerText.components(separatedBy: "\r\n")
        guard let requestLine = lines.first else { return nil }
        let requestParts = requestLine.split(separator: " ", maxSplits: 2).map(String.init)
        guard requestParts.count == 3 else { return nil }

        var headers: [String: String] = [:]
        for line in lines.dropFirst() {
            guard let colon = line.firstIndex(of: ":") else { continue }
            let key = String(line[..<colon]).trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
            let value = String(line[line.index(after: colon)...]).trimmingCharacters(in: .whitespacesAndNewlines)
            headers[key] = value
        }

        let bodyStart = headerRange.upperBound
        let expectedLength = Int(headers["content-length"] ?? "0") ?? 0
        guard data.count - bodyStart >= expectedLength else { return nil }
        let body = expectedLength > 0 ? data.subdata(in: bodyStart..<(bodyStart + expectedLength)) : Data()

        let rawTarget = requestParts[1]
        let pieces = rawTarget.split(separator: "?", maxSplits: 1).map(String.init)
        return HTTPRequest(
            method: requestParts[0].uppercased(),
            path: pieces.first ?? "/",
            query: pieces.count > 1 ? pieces[1] : "",
            version: requestParts[2],
            headers: headers,
            body: body
        )
    }
}

struct HTTPResponse {
    let statusCode: Int
    let reason: String
    let headers: [String: String]
    let body: Data

    static func json(_ payload: [String: Any], statusCode: Int = 200, reason: String = "OK") -> HTTPResponse {
        let data = (try? JSONSerialization.data(withJSONObject: payload, options: [.prettyPrinted, .sortedKeys])) ?? Data("{}".utf8)
        return HTTPResponse(
            statusCode: statusCode,
            reason: reason,
            headers: [
                "Content-Type": "application/json; charset=utf-8",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, X-AGENT-PHONE-TOKEN, X-APKCLAW-TOKEN, X-LUMI-LAUNCHER-ID, X-LUMI-TIMESTAMP, X-LUMI-NONCE, X-LUMI-SIGNATURE, X-LUMI-BODY-SHA256"
            ],
            body: data
        )
    }

    static func html(_ text: String) -> HTTPResponse {
        HTTPResponse(
            statusCode: 200,
            reason: "OK",
            headers: [
                "Content-Type": "text/html; charset=utf-8",
                "Access-Control-Allow-Origin": "*"
            ],
            body: Data(text.utf8)
        )
    }

    static func options() -> HTTPResponse {
        HTTPResponse.json(["success": true])
    }

    static func error(_ message: String, statusCode: Int = 400, reason: String = "Bad Request") -> HTTPResponse {
        HTTPResponse.json(["success": false, "error": message], statusCode: statusCode, reason: reason)
    }

    func serialize() -> Data {
        var head = "HTTP/1.1 \(statusCode) \(reason)\r\n"
        var mergedHeaders = headers
        mergedHeaders["Content-Length"] = "\(body.count)"
        mergedHeaders["Connection"] = "close"
        for (key, value) in mergedHeaders {
            head += "\(key): \(value)\r\n"
        }
        head += "\r\n"
        var data = Data(head.utf8)
        data.append(body)
        return data
    }
}

func codableToDictionary<T: Encodable>(_ value: T) -> [String: Any] {
    guard
        let data = try? JSONEncoder().encode(value),
        let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
    else {
        return [:]
    }
    return object
}
