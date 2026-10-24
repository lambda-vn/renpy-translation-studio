// Builds the installable application: `npm run bundle`.
//
// Two executables ship together, the way 1.x shipped `rts-mcp` beside the
// application: the Tauri app, and the stdio MCP server a client launches.
// Tauri only knows about the second as a sidecar (`externalBin`), which
// must exist on disk under a target-triple suffix before the bundler runs
// — and, being checked at compile time, would also break plain
// `tauri dev` if it were declared in tauri.conf.json. It lives in
// tauri.bundle.conf.json instead, merged here and nowhere else.
//
// Tauri does not cross-compile any more than flet did: each system builds
// its own bundles, hence one CI runner per system.

import { spawnSync } from 'node:child_process';
import { copyFileSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const tauriDir = join(root, 'src-tauri');
const exe = process.platform === 'win32' ? '.exe' : '';

function run(command, args) {
	const result = spawnSync(command, args, { stdio: 'inherit', cwd: root });
	if (result.status !== 0) {
		console.error(`\n${command} ${args.join(' ')} failed (${result.status ?? result.error}).`);
		process.exit(result.status ?? 1);
	}
}

function hostTriple() {
	const out = spawnSync('rustc', ['-vV'], { encoding: 'utf8' }).stdout ?? '';
	const match = out.match(/^host: (.+)$/m);
	if (!match) {
		console.error('Could not read the host target triple from `rustc -vV`.');
		process.exit(1);
	}
	return match[1].trim();
}

// One format family per system. MSI is left out on purpose: WiX only
// accepts a numeric pre-release identifier, and "rc.1" is not one.
const bundles = {
	win32: ['nsis'],
	darwin: ['app', 'dmg'],
	linux: ['deb', 'appimage']
}[process.platform];

if (!bundles) {
	console.error(`No bundle formats defined for ${process.platform}.`);
	process.exit(1);
}

const triple = hostTriple();

run('cargo', [
	'build',
	'--release',
	'--bin',
	'rts-mcp',
	'--manifest-path',
	join(tauriDir, 'Cargo.toml')
]);

const staged = join(tauriDir, 'binaries');
mkdirSync(staged, { recursive: true });
copyFileSync(join(tauriDir, 'target', 'release', `rts-mcp${exe}`), join(staged, `rts-mcp-${triple}${exe}`));
console.log(`Staged rts-mcp-${triple}${exe}`);

run(process.execPath, [
	join(root, 'node_modules', '@tauri-apps', 'cli', 'tauri.js'),
	'build',
	'--config',
	join(tauriDir, 'tauri.bundle.conf.json'),
	'--bundles',
	bundles.join(',')
]);
