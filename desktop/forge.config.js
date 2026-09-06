// Electron Forge packaging.
//
// The frozen Python engine is shipped as an extraResource — a plain folder
// beside the app rather than something inside the asar, because it contains
// native libraries that have to exist as real files on disk to be loadable.
// main.js looks for it there first and only falls back to a Python on PATH.
//
// Build the engine before packaging; `npm run make` does both in order.

const fs = require("node:fs");
const path = require("node:path");

const ENGINE = path.resolve(__dirname, "..", "dist", "engine", "saidso-engine");

if (!fs.existsSync(ENGINE)) {
  // Failing here with an explanation beats shipping an app whose engine is
  // missing and which only says so when someone opens it.
  throw new Error(
    `No engine build at ${ENGINE}.\n` +
      "Build it first, from the repository root:\n" +
      "  pyinstaller packaging/saidso-engine.spec --noconfirm " +
      "--distpath dist/engine --workpath build/pyinstaller"
  );
}

module.exports = {
  packagerConfig: {
    name: "saidso",
    executableName: process.platform === "win32" ? "saidso" : "saidso",
    asar: true,
    extraResource: [ENGINE],
    prune: true,
    ignore: [/^\/forge\.config\.js$/, /^\/README\.md$/],
  },
  rebuildConfig: {},
  makers: [
    {
      name: "@electron-forge/maker-squirrel",
      platforms: ["win32"],
      config: {
        name: "saidso",
        // Squirrel builds a NuGet package underneath, and these are required
        // there — the build otherwise fails at the very last step, after the
        // whole app has been packaged.
        authors: "JaviGold",
        description: "Record, transcribe and organise meetings on your own machine.",
        setupExe: "saidso-setup.exe",
        noMsi: true,
      },
    },
    {
      name: "@electron-forge/maker-zip",
      platforms: ["darwin", "linux", "win32"],
    },
  ],
  plugins: [],
};
