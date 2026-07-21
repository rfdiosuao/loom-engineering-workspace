import Foundation

struct AgentTask: Codable {
    var taskId: String
    var status: String
    var createdAt: Int64
    var updatedAt: Int64
    var summary: String
    var result: [String: String]
    var events: [[String: String]]
}

final class AgentTaskStore {
    private var tasks: [String: AgentTask] = [:]
    private let lock = NSLock()

    func create(prompt: String) -> AgentTask {
        let now = Int64(Date().timeIntervalSince1970 * 1000)
        let id = "ios-\(UUID().uuidString.lowercased())"
        let task = AgentTask(
            taskId: id,
            status: "completed",
            createdAt: now,
            updatedAt: now,
            summary: "iOSClaw Lite received the task. Arbitrary app control requires the future WebDriverAgent mode.",
            result: [
                "prompt": prompt,
                "mode": "iosclaw-lite",
                "control": "unsupported_without_webdriveragent"
            ],
            events: [
                ["type": "accepted", "message": "Task accepted by iOSClaw Lite."],
                ["type": "completed", "message": "No mutating iOS action was executed."]
            ]
        )
        lock.lock()
        tasks[id] = task
        lock.unlock()
        return task
    }

    func get(_ id: String) -> AgentTask? {
        lock.lock()
        defer { lock.unlock() }
        return tasks[id]
    }

    func cancel(_ id: String) -> AgentTask? {
        lock.lock()
        defer { lock.unlock() }
        guard var task = tasks[id] else { return nil }
        task.status = "cancelled"
        task.updatedAt = Int64(Date().timeIntervalSince1970 * 1000)
        task.events.append(["type": "cancelled", "message": "Task cancelled."])
        tasks[id] = task
        return task
    }
}
