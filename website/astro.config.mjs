import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

const posthogScript = `!function(t,e){var o,n,p,r;e.__SV||(window.posthog=e,e._i=[],e.init=function(i,s,a){function g(t,e){var o=e.split(".");2==o.length&&(t=t[o[0]],e=o[1]),t[e]=function(){t.push([e].concat(Array.prototype.slice.call(arguments,0)))}}(p=t.createElement("script")).type="text/javascript",p.crossOrigin="anonymous",p.async=!0,p.src=s.api_host.replace(".i.posthog.com","-assets.i.posthog.com")+"/static/array.js",(r=t.getElementsByTagName("script")[0]).parentNode.insertBefore(p,r);var u=e;for(void 0!==a?u=e[a]=[]:a="posthog",u.people=u.people||[],u.toString=function(t){var e="posthog";return"posthog"!==a&&(e+="."+a),t||(e+=" (stub)"),e},u.people.toString=function(){return u.toString(1)+".people (stub)"},o="init capture identify alias people.set people.set_once people.unset reset opt_in_capturing opt_out_capturing has_opted_in_capturing has_opted_out_capturing clear_opt_in_out_capturing onFeatureFlags getFeatureFlag getFeatureFlagPayload isFeatureEnabled reloadFeatureFlags updateEarlyAccessFeatureEnrollment getEarlyAccessFeatures getSurveys getActiveMatchingSurveys renderSurvey canRenderSurvey captureException startSessionRecording stopSessionRecording sessionRecordingStarted capturePerformance captureTraceFeedback captureTraceMetric startExceptionCapture stopExceptionCapture".split(" "),n=0;n<o.length;n++)g(u,o[n]);e._i.push([i,s,a])},e.__SV=1)}(document,window.posthog||[]);posthog.init('phc_qXkp5FBQfrqHQwkqf3ys8iSoGoMYw2tpTHXGugXJhP8V',{api_host:'https://us.i.posthog.com',defaults:'2026-05-30',person_profiles:'identified_only',capture_pageview:true,capture_pageleave:true,autocapture:{dom_event_allowlist:['click'],element_allowlist:['a','button']},disable_session_recording:true});`;

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
      { label: 'Start here', items: [{ label: 'Quick start', link: '/quick-start/' }] },
      { label: 'Build', items: [{ label: 'Model-free endpoint', link: '/build/direct-execution/' }, { label: 'Agent-backed choice', link: '/build/agent-choice/' }] },
      { label: 'Reference', items: [{ label: 'Operations & bindings', link: '/reference/operations/' }] },
      { label: 'Guides', items: [{ label: 'Architecture & safety', link: '/architecture/' }, { label: 'Capabilities', link: '/capabilities/' }, { label: 'Operations & troubleshooting', link: '/guides/operations/' }] },
      { label: 'Internals', items: [{ label: 'Execution flow', link: '/internals/execution/' }] },
      { label: 'ModePot', link: 'https://modepot.io/' },
    ],
  })],
});
