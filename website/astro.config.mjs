import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

export default defineConfig({
  site: 'https://summonpot.modepot.io',
  integrations: [starlight({
    title: 'Summonpot',
    description: 'Modernize APIs for the AI era with one simple contract.',
    social: [{ icon: 'github', label: 'GitHub', href: 'https://github.com/tugrulguner/summonpot' }],
    favicon: '/favicon.svg',
    customCss: ['./src/styles/custom.css'],
    head: [
      { tag: 'meta', attrs: { property: 'og:type', content: 'website' } },
      { tag: 'meta', attrs: { property: 'og:site_name', content: 'Summonpot' } },
      { tag: 'meta', attrs: { name: 'twitter:card', content: 'summary_large_image' } },
      { tag: 'meta', attrs: { name: 'twitter:title', content: 'Summonpot — APIs for the AI era' } },
      { tag: 'meta', attrs: { name: 'twitter:description', content: 'One simple contract: deterministic operations plus bounded agent-owned decisions.' } },
      { tag: 'meta', attrs: { property: 'og:image', content: 'https://summonpot.modepot.io/social-card.png' } },
      { tag: 'meta', attrs: { name: 'twitter:image', content: 'https://summonpot.modepot.io/social-card.png' } },
      { tag: 'meta', attrs: { name: 'robots', content: 'index,follow' } },
      { tag: 'script', attrs: { type: 'application/ld+json' }, children: JSON.stringify({ '@context': 'https://schema.org', '@type': 'SoftwareApplication', name: 'Summonpot', applicationCategory: 'DeveloperApplication', operatingSystem: 'Python 3.11–3.13', description: 'A contract-first Python framework that modernizes APIs for the AI era with deterministic operations and bounded agent-owned decisions.', url: 'https://summonpot.modepot.io', codeRepository: 'https://github.com/tugrulguner/summonpot', license: 'https://opensource.org/license/mit' }) },
    ],
    sidebar: [
      { label: 'Start here', items: [{ label: 'Quick start', link: '/quick-start/' }] },
      { label: 'Guides', items: [{ label: 'Architecture & safety', link: '/architecture/' }, { label: 'Capabilities', link: '/capabilities/' }] },
    ],
  })],
});
