import type {MetadataRoute} from 'next';

export default function manifest(): MetadataRoute.Manifest {
  return {
    id: '/', name: 'Near · Here for your everyday', short_name: 'Near',
    description: 'Create a fictional companion and keep the moments you choose to share.', lang: 'en',
    start_url: '/', scope: '/', display: 'standalone',
    background_color: '#f5f5ef', theme_color: '#315c4d',
    icons: [
      {src: '/icons/icon-192.png', sizes: '192x192', type: 'image/png', purpose: 'any'},
      {src: '/icons/icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any'},
      {src: '/icons/icon-maskable.png', sizes: '512x512', type: 'image/png', purpose: 'maskable'},
    ],
  };
}
