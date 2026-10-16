// Company pages need the live API and the slug at runtime: skip prerender, render in the browser.
export const prerender = false;
export const ssr = false;

export function load({ params }: { params: { slug: string } }) {
	return { slug: params.slug };
}
