"""新界面的结构化会话存储；独立建表，不改写旧版聊天数据。"""
from contextlib import contextmanager
from datetime import datetime, timezone
import html
import json
from pathlib import Path
import re
import sqlite3
import uuid


def now():
    return datetime.now(timezone.utc).isoformat()


class ThreadStore:
    """消息与运行一次事务收尾，刷新页面不依赖浏览器内存恢复对话。"""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as database:
            database.execute("PRAGMA journal_mode=WAL")
            database.executescript("""
                CREATE TABLE IF NOT EXISTS threads (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS web_messages (
                    id TEXT PRIMARY KEY, thread_id TEXT NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
                    role TEXT NOT NULL, content TEXT NOT NULL, metadata TEXT NOT NULL,
                    created_at TEXT NOT NULL, ordinal INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, thread_id TEXT NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
                    message_id TEXT NOT NULL, status TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS web_messages_order ON web_messages(thread_id, ordinal);
            """)

    @contextmanager
    def connection(self):
        database = sqlite3.connect(self.path, timeout=30)
        database.row_factory = sqlite3.Row
        database.execute("PRAGMA foreign_keys=ON")
        try:
            with database:
                yield database
        finally:
            database.close()

    def recover(self):
        """单进程启动时标记上次中断的运行，不伪装成已完成回答。"""
        with self.connection() as database:
            for run in database.execute("SELECT * FROM runs WHERE status='running'").fetchall():
                database.execute("UPDATE runs SET status='interrupted', updated_at=? WHERE id=?", (now(), run["id"]))
                database.execute("UPDATE web_messages SET metadata=? WHERE id=?",
                                 (json.dumps({"status": "interrupted", "run_id": run["id"]}), run["message_id"]))

    def create_thread(self, title="新对话"):
        thread_id, timestamp = uuid.uuid4().hex, now()
        with self.connection() as database:
            database.execute("INSERT INTO threads VALUES (?, ?, ?, ?)", (thread_id, title, timestamp, timestamp))
        return self.get_thread(thread_id)

    def list_threads(self):
        with self.connection() as database:
            return [dict(row) for row in database.execute("SELECT * FROM threads ORDER BY updated_at DESC")]

    def get_thread(self, thread_id):
        with self.connection() as database:
            row = database.execute("SELECT * FROM threads WHERE id=?", (thread_id,)).fetchone()
            if row is None:
                raise KeyError(thread_id)
            return dict(row)

    def messages(self, thread_id):
        self.get_thread(thread_id)
        with self.connection() as database:
            return [dict(row, metadata=json.loads(row["metadata"])) for row in database.execute(
                "SELECT id,role,content,metadata,created_at FROM web_messages WHERE thread_id=? ORDER BY ordinal", (thread_id,))]

    def start_run(self, thread_id, run_id, text):
        message_id, timestamp = uuid.uuid4().hex, now()
        self.get_thread(thread_id)
        with self.connection() as database:
            ordinal = database.execute("SELECT COALESCE(MAX(ordinal),0) FROM web_messages WHERE thread_id=?", (thread_id,)).fetchone()[0]
            # run_id 唯一约束阻止重试请求重复写入同一轮消息。
            database.execute("INSERT INTO runs VALUES (?,?,?,?,?,?)", (run_id, thread_id, message_id, "running", timestamp, timestamp))
            database.executemany("INSERT INTO web_messages VALUES (?,?,?,?,?,?,?)", [
                (uuid.uuid4().hex, thread_id, "user", text, "{}", timestamp, ordinal + 1),
                (message_id, thread_id, "assistant", "", json.dumps({"status": "running", "run_id": run_id}), timestamp, ordinal + 2),
            ])
            database.execute("UPDATE threads SET title=CASE WHEN title='新对话' THEN ? ELSE title END,updated_at=? WHERE id=?",
                             (text[:32], timestamp, thread_id))
        return message_id

    def finish_run(self, run_id, content, metadata, status):
        with self.connection() as database:
            row = database.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                raise KeyError(run_id)
            metadata = dict(metadata, status=status, run_id=run_id)
            database.execute("UPDATE web_messages SET content=?,metadata=? WHERE id=?",
                             (content, json.dumps(metadata, ensure_ascii=False), row["message_id"]))
            database.execute("UPDATE runs SET status=?,updated_at=? WHERE id=?", (status, now(), run_id))
            database.execute("UPDATE threads SET updated_at=? WHERE id=?", (now(), row["thread_id"]))

    def get_run(self, run_id):
        with self.connection() as database:
            row = database.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                raise KeyError(run_id)
            return dict(row)

    def delete_thread(self, thread_id):
        self.get_thread(thread_id)
        with self.connection() as database:
            database.execute("DELETE FROM threads WHERE id=?", (thread_id,))


def legacy_messages(path):
    """只读适配旧 HTML 消息；不执行 HTML、不修改数据库，也不自动复制历史。"""
    path = Path(path)
    if not path.is_file():
        return []
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as database:
        try:
            rows = database.execute("SELECT id,role,content FROM messages WHERE conversation_id=1 ORDER BY id").fetchall()
        except sqlite3.OperationalError:
            return []
    result = []
    for message_id, role, content in rows:
        if role not in {"user", "assistant"}:
            continue
        if role == "assistant":
            # 只提取正文，旧来源 HTML 不作为新界面的可执行内容。
            content = re.sub(r"^<details\b.*?</details>\s*", "", content, count=1, flags=re.S)
            content = content.split("<!-- rag-sources -->", 1)[0]
            content = html.unescape(re.sub(r"<[^>]+>", "", content))
        result.append(dict(id=f"legacy-{message_id}", role=role, content=content.strip(),
                           metadata={"status": "completed", "legacy": True}))
    return result
