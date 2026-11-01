// Node 18 iOS fallback: a minimal `node:sqlite` implementation for the OpenCode CLI.
//
// The shipped iPhoneOS Node 18 runtime has no `node:sqlite` module. This module is
// inlined into the iOS Node 18 bundle at build time (Vite virtual module, see
// patches/opencode/0007-node18-ios-compat.patch) and provides the tiny slice of the
// Node 22 `DatabaseSync`/`StatementSync` API that `packages/core/src/database/sqlite.node.ts`
// uses, backed by sql.js (SQLite compiled to WebAssembly, MIT).
//
// It is deliberately synchronous after a one-time WebAssembly init (top-level await), because
// the SQLite client API it implements is synchronous. Persistence is a best-effort whole-file
// write: the database is exported and atomically rewritten at most every FLUSH_INTERVAL_MS and
// unconditionally on close(). This is slower than native SQLite but adequate for the CLI's
// session/config database, and it keeps data across processes.
//
// Assets (staged next to the bundle by scripts/build-opencode-bundle.sh):
//   assets/node18-sqlite/sql-wasm.js
//   assets/node18-sqlite/sql-wasm.wasm

import { createRequire } from "node:module"
import { mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"

const FLUSH_INTERVAL_MS = 250
const require = createRequire(import.meta.url)
const assets = process.env.OPENCODE_NODE_ASSETS_DIR ?? path.join(path.dirname(fileURLToPath(import.meta.url)), "assets")
const initSqlJs = require(path.join(assets, "node18-sqlite", "sql-wasm.js"))
const wasmBinary = readFileSync(path.join(assets, "node18-sqlite", "sql-wasm.wasm"))
const SQL = await initSqlJs({ wasmBinary })

class StatementSync {
  constructor(database, sql) {
    this.database = database
    this.sql = sql
    this.arrays = false
  }
  setReadBigInts() {
    // sql.js returns JS numbers; SafeIntegers mode is not implemented by this fallback.
  }
  setReturnArrays(value) {
    this.arrays = Boolean(value)
  }
  all(...params) {
    const database = this.database
    if (database.closed) throw new Error("database is closed")
    const statement = database.impl.prepare(this.sql)
    try {
      if (params.length > 0) statement.bind(params)
      const rows = []
      while (statement.step()) rows.push(this.arrays ? statement.get() : statement.getAsObject())
      return rows
    } finally {
      statement.free()
      database.touch()
    }
  }
  get(...params) {
    return this.all(...params)[0]
  }
  run(...params) {
    this.all(...params)
    return { changes: 0, lastInsertRowid: 0 }
  }
}

export class DatabaseSync {
  constructor(filename, options = {}) {
    this.filename = filename
    this.readOnly = options.readOnly === true
    this.closed = false
    this.dirty = false
    this.lastFlush = Date.now()
    const persisted = this.readOnly || filename === ":memory:" || !filename ? undefined : tryRead(filename)
    this.impl = persisted ? new SQL.Database(persisted) : new SQL.Database()
    this.impl.exec("PRAGMA foreign_keys = ON")
    openDatabases.add(this)
  }
  exec(sql) {
    // The native runtime opens the database in WAL mode; sql.js has no on-disk WAL. Keep the
    // rollback-journal format this shim persists so an existing file stays readable.
    if (/^\s*PRAGMA\s+journal_mode\s*=/i.test(sql)) return
    this.impl.exec(sql)
    this.touch()
  }
  prepare(sql) {
    return new StatementSync(this, sql)
  }
  touch() {
    this.dirty = true
    if (Date.now() - this.lastFlush >= FLUSH_INTERVAL_MS) this.flush()
  }
  flush(force = false) {
    if (this.readOnly || !this.dirty || !this.filename || this.filename === ":memory:") return
    if (!force && Date.now() - this.lastFlush < FLUSH_INTERVAL_MS) return
    const bytes = this.impl.export()
    const target = this.filename
    const temporary = `${target}.${process.pid}.tmp`
    mkdirSync(path.dirname(target), { recursive: true })
    writeFileSync(temporary, bytes)
    renameSync(temporary, target)
    this.dirty = false
    this.lastFlush = Date.now()
  }
  close() {
    if (this.closed) return
    this.flush(true)
    this.impl.close()
    this.closed = true
    openDatabases.delete(this)
  }
  loadExtension() {
    throw new Error("sqlite extension loading is not supported by the Node 18 iOS fallback")
  }
}

function tryRead(file) {
  try {
    return readFileSync(file)
  } catch {
    return undefined
  }
}

// Best-effort flush of any databases still open when the process exits.
const openDatabases = new Set()
process.on("exit", () => {
  for (const database of openDatabases) database.flush(true)
})

