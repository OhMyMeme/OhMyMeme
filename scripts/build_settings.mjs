import { access, mkdir, readFile, rm, writeFile } from "node:fs/promises"
import { constants } from "node:fs"
import { dirname, resolve } from "node:path"
import { fileURLToPath } from "node:url"
import settingsModules from "../src/ohmymeme/presentation/frontend/settings/entry.mjs"

const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..")
const sourceRoot = resolve(
  projectRoot,
  "src/ohmymeme/presentation/frontend/settings",
)
const runtimeEntry = resolve(projectRoot, "src/webui/settings.js")
const legacyImports = resolve(sourceRoot, "features/imports.js")
const importsRoot = resolve(sourceRoot, "features/imports")
const legacySync = resolve(sourceRoot, "features/sync.js")
const syncRoot = resolve(sourceRoot, "features/sync")

const sections = [
  ["core/runtime.js", 1, 103],
  ["features/logs.js", 104, 150],
  ["features/lan.js", 152, 274],
  ["features/base.js", 276, 358],
  ["features/storage.js", 360, 434],
  ["features/sync.js", 436, 855],
  ["features/imports.js", 856, 1685],
  ["core/window.js", 1686, 1769],
  ["features/update.js", 1770, 1866],
  ["features/danger.js", 1868, 1923],
  ["core/init.js", 1927, 1966],
]

async function exists(path) {
  try {
    await access(path, constants.F_OK)
    return true
  } catch {
    return false
  }
}

async function bootstrapSources() {
  const runtime = await readFile(runtimeEntry, "utf8")
  const lines = runtime.split(/\r?\n/)

  for (const [name, start, end] of sections) {
    const destination = resolve(sourceRoot, name)
    await mkdir(dirname(destination), { recursive: true })
    await writeFile(destination, `${lines.slice(start - 1, end).join("\n")}\n`, "utf8")
  }
}

async function splitImportControllers() {
  if (!(await exists(legacyImports))) return

  const source = (await readFile(legacyImports, "utf8")).split(/\r?\n/)
  const controllers = [
    ["qq.js", 1, 115],
    ["douyin.js", 116, 249],
    ["telegram.js", 250, 426],
    ["wechat.js", 427, 647],
    ["qqnt.js", 648, 830],
  ]

  await mkdir(importsRoot, { recursive: true })
  await Promise.all(
    controllers.map(([name, start, end]) =>
      writeFile(
        resolve(importsRoot, name),
        `${source.slice(start - 1, end).join("\n")}\n`,
        "utf8",
      ),
    ),
  )
  await rm(legacyImports)
}

async function splitSyncControllers() {
  if (!(await exists(legacySync))) return

  const source = (await readFile(legacySync, "utf8")).split(/\r?\n/)
  await mkdir(syncRoot, { recursive: true })
  await Promise.all([
    writeFile(
      resolve(syncRoot, "settings.js"),
      `${source.slice(0, 202).join("\n")}\n`,
      "utf8",
    ),
    writeFile(
      resolve(syncRoot, "operations.js"),
      `${source.slice(202).join("\n")}\n`,
      "utf8",
    ),
  ])
  await rm(legacySync)
}

async function assembleRuntime() {
  const sources = await Promise.all(
    settingsModules.map((name) => readFile(resolve(sourceRoot, name), "utf8")),
  )
  await writeFile(runtimeEntry, sources.join("\n"), "utf8")
}

if (!(await exists(resolve(sourceRoot, settingsModules[0])))) {
  await bootstrapSources()
}

await splitImportControllers()
await splitSyncControllers()
await assembleRuntime()
