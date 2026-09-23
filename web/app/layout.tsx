import type { Metadata, Viewport } from 'next';
import './style.css';
import './enhancements.css';
export const metadata: Metadata = {
  title: 'Near · Here for your everyday', description: 'Private fictional AI companions',
  applicationName: 'Near', appleWebApp: {capable: true, title: 'Near', statusBarStyle: 'default'},
  icons: {icon: '/icons/icon-192.png', apple: '/icons/apple-touch-icon.png'},
};
export const viewport: Viewport = {themeColor: '#315c4d', width: 'device-width', initialScale: 1};
export default function Layout({children}: Readonly<{children: React.ReactNode}>) {
  return <html lang="en"><body>{children}</body></html>;
}
