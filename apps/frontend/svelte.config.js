import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

/** @type {import('@sveltejs/kit').Config} */
const config = {
	preprocess: vitePreprocess(),
	kit: {
		// Static build with an SPA fallback: the UI talks to apps/backend over HTTP and is served
		// as plain files. Pages that can be prerendered are; everything else uses the fallback.
		adapter: adapter({ fallback: '200.html' }),
		prerender: {
			// The rail links to /new before the onboarding page exists (Task 7): the crawler may
			// meet that one 404. Delete this handler when the page is added.
			handleHttpError: ({ path, message }) => {
				if (path === '/new') return;
				throw new Error(message);
			}
		}
	}
};

export default config;
