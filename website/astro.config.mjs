import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import { posthogScript } from './src/analytics/posthog.js';

const structuredData = {
  '@context': 'https://schema.org',
  '@graph': [
    {
      '@type': 'SoftwareApplication',
      name: 'Summonpot',
      applicationCategory: 'DeveloperApplication',
      operatingSystem: 'Python 3.11 through 3.14',
      description: 'A contract-first Python framework for deterministic operations and explicitly bounded agent-owned decisions.',
      url: 'https://summonpot.modepot.io/',
      codeRepository: 'https://github.com/tugrulguner/summonpot',
      installUrl: 'https://pypi.org/project/summonpot/',
      license: 'https://opensource.org/license/mit',
      isPartOf: { '@type': 'Organization', name: 'ModePot', url: 'https://modepot.io/' },
    },
    { '@type': 'WebSite', name: 'Summonpot documentation', url: 'https://summonpot.modepot.io/', inLanguage: 'en' },
  ],
};

export default defineConfig({
  site: 'https://summonpot.modepot.io',
  integrations: [starlight({
    title: 'Summonpot',
    description: 'Modernize APIs for the AI era with one simple contract.',
    social: [{ icon: 'github', label: 'GitHub', href: 'https://github.com/tugrulguner/summonpot' }],
    favicon: '/favicon.svg',
    customCss: ['./src/styles/custom.css'],
    components: { Header: './src/components/FamilyHeader.astro' },
    head: [
      { tag: 'script', attrs: {}, content: posthogScript },
      { tag: 'meta', attrs: { property: 'og:type', content: 'website' } },
      { tag: 'meta', attrs: { property: 'og:site_name', content: 'Summonpot' } },
      { tag: 'meta', attrs: { name: 'twitter:card', content: 'summary_large_image' } },
      { tag: 'meta', attrs: { name: 'twitter:title', content: 'Summonpot — APIs for the AI era' } },
      { tag: 'meta', attrs: { name: 'twitter:description', content: 'One simple contract: deterministic operations plus bounded agent-owned decisions.' } },
      { tag: 'meta', attrs: { property: 'og:image', content: 'https://summonpot.modepot.io/social-card-v2.png' } },
      { tag: 'meta', attrs: { name: 'twitter:image', content: 'https://summonpot.modepot.io/social-card-v2.png' } },
      { tag: 'meta', attrs: { name: 'robots', content: 'index,follow' } },
      { tag: 'link', attrs: { rel: 'alternate', type: 'text/plain', href: '/llms.txt', title: 'Summonpot summary for AI agents' } },
      { tag: 'script', attrs: { type: 'application/ld+json' }, content: JSON.stringify(structuredData) },
    ],
    sidebar: [
      { label: 'Start here', items: [{ label: 'Quick start', link: '/quick-start/' }, { label: 'README (current source)', link: '/source/readme/' }, { label: 'Roadmap (planned work)', link: '/source/roadmap/' }] },
      { label: 'Build', items: [{ label: 'Model-free endpoint', link: '/build/direct-execution/' }, { label: 'Agent-backed choice', link: '/build/agent-choice/' }] },
      { label: 'Reference', items: [{ label: 'Operations & bindings', link: '/reference/operations/' }] },
      { label: 'Guides', items: [{ label: 'Architecture & safety', link: '/architecture/' }, { label: 'Capabilities', link: '/capabilities/' }, { label: 'Operations & troubleshooting', link: '/guides/operations/' }] },
      { label: 'Internals', items: [{ label: 'Execution flow', link: '/internals/execution/' }] },
      { label: 'ModePot', link: 'https://modepot.io/' },
    ],
  })],
});
