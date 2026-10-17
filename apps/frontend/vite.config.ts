import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vitest/config';

// Vite runs this file in Node; the app has no Node types, and this is all it reads.
declare const process: { env: Record<string, string | undefined> };
/** The bits of Vite's proxy (an http-proxy server) the API proxy listens to, for the same reason. */
interface ProxyEvents {
	on(
		event: 'proxyRes',
		listener: (
			proxyRes: { on(event: 'close', listener: () => void): void },
			req: unknown,
			res: { writableEnded: boolean; destroy(): void }
		) => void
	): void;
}

export default defineConfig({
	plugins: [sveltekit()],
	server: {
		// `make api` serves the backend here (API_PORT moves it); the UI always calls it through /api.
		proxy: {
			'/api': {
				target: `http://127.0.0.1:${process.env.API_PORT ?? 8000}`,
				// When the API restarts (`--reload`) it drops its event streams without ending them,
				// and the proxy would keep the browser's side open and silent: the page never hears
				// that it should reconnect, so a build's banner stays at "step 1". Drop that side too.
				configure: (proxy) => {
					(proxy as unknown as ProxyEvents).on('proxyRes', (proxyRes, _req, res) => {
						proxyRes.on('close', () => {
							if (!res.writableEnded) res.destroy();
						});
					});
				}
			}
		}
	},
	test: {
		include: ['src/**/*.test.ts']
	}
});
