import {themes as prismThemes} from 'prism-react-renderer';
import type {Config} from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';

const config: Config = {
  title: 'PolyEdge Docs',
  tagline: 'AI-Powered Prediction Market Trading Bot',
  favicon: 'img/favicon.ico',

  future: {
    v4: true,
  },

  url: 'https://polyedge.aitradepulse.com',
  baseUrl: '/docs/',
  trailingSlash: false,

  organizationName: 'polyedge',
  projectName: 'polyedge',

  onBrokenLinks: 'throw',

  markdown: {
    hooks: {
      onBrokenMarkdownLinks: 'warn',
    },
  },

  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
  },

  presets: [
    [
      'classic',
      {
        docs: {
          sidebarPath: './sidebars.ts',
          routeBasePath: '/',
          exclude: ['**/AGENTS.md'],
        },
        blog: false,
        theme: {
          customCss: './src/css/custom.css',
        },
      } satisfies Preset.Options,
    ],
  ],

  themeConfig: {
    image: 'img/polyedge-social-card.jpg',
    colorMode: {
      defaultMode: 'dark',
      disableSwitch: false,
      respectPrefersColorScheme: true,
    },
    navbar: {
      title: 'PolyEdge',
      logo: {
        alt: 'PolyEdge Logo',
        src: 'img/logo.svg',
      },
      items: [
        {
          type: 'docSidebar',
          sidebarId: 'docsSidebar',
          position: 'left',
          label: 'Docs',
        },
        {
          to: '/docs/api-reference/overview',
          label: 'API Reference',
          position: 'left',
        },
        {
          to: '/docs/strategies/btc-momentum',
          label: 'Strategies',
          position: 'left',
        },
        {
          href: 'https://github.com/polyedge/polyedge',
          label: 'GitHub',
          position: 'right',
        },
      ],
    },
    footer: {
      style: 'dark',
      links: [
        {
          title: 'Getting Started',
          items: [
            {
              label: 'Introduction',
              to: '/docs/intro',
            },
            {
              label: 'Quick Start (Traders)',
              to: '/docs/getting-started/quick-start-trader',
            },
            {
              label: 'Quick Start (Developers)',
              to: '/docs/getting-started/quick-start-developer',
            },
          ],
        },
        {
          title: 'Reference',
          items: [
            {
              label: 'Dashboard',
              to: '/docs/dashboard/overview-tab',
            },
            {
              label: 'Admin Panel',
              to: '/docs/admin/system-status',
            },
            {
              label: 'API Reference',
              to: '/docs/api-reference/overview',
            },
          ],
        },
        {
          title: 'More',
          items: [
            {
              label: 'Architecture',
              to: '/docs/architecture/overview',
            },
            {
              label: 'Configuration',
              to: '/docs/configuration/environment-variables',
            },
            {
              label: 'GitHub',
              href: 'https://github.com/polyedge/polyedge',
            },
          ],
        },
      ],
      copyright: `Copyright \u00a9 ${new Date().getFullYear()} PolyEdge. Built with Docusaurus.`,
    },
    prism: {
      theme: prismThemes.github,
      darkTheme: prismThemes.dracula,
      additionalLanguages: ['python', 'bash', 'json', 'yaml', 'docker'],
    },
  } satisfies Preset.ThemeConfig,
};

export default config;
