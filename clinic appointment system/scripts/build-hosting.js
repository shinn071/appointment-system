const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
const publicDirectory = path.join(root, 'public');

function readLocalEnvironment() {
  const file = path.join(root, '.env.local');
  if (!fs.existsSync(file)) return {};

  return Object.fromEntries(
    fs.readFileSync(file, 'utf8')
      .split(/\r?\n/)
      .map(line => line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$/))
      .filter(Boolean)
      .map(([, key, value]) => [key, value.replace(/^(['"])(.*)\1$/, '$2')])
  );
}

const localEnvironment = readLocalEnvironment();
const firebaseConfig = {
  apiKey: process.env.FIREBASE_API_KEY || localEnvironment.FIREBASE_API_KEY || '',
  authDomain: process.env.FIREBASE_AUTH_DOMAIN || localEnvironment.FIREBASE_AUTH_DOMAIN || '',
  projectId: process.env.FIREBASE_PROJECT_ID || localEnvironment.FIREBASE_PROJECT_ID || '',
  appId: process.env.FIREBASE_APP_ID || localEnvironment.FIREBASE_APP_ID || ''
};

if (Object.values(firebaseConfig).some(value => !value.trim())) {
  throw new Error('Firebase web config is incomplete. Set FIREBASE_API_KEY, FIREBASE_AUTH_DOMAIN, FIREBASE_PROJECT_ID, and FIREBASE_APP_ID in .env.local or the build environment.');
}

fs.mkdirSync(path.join(publicDirectory, 'static'), { recursive: true });
const index = fs.readFileSync(path.join(root, 'index.html'), 'utf8')
  .replace(
    '<script src="static/app.js" defer></script>',
    '<script src="static/firebase-config.js"></script>\n  <script src="static/app.js" defer></script>'
  );
fs.writeFileSync(path.join(publicDirectory, 'index.html'), index);
fs.cpSync(path.join(root, 'static'), path.join(publicDirectory, 'static'), { recursive: true });
fs.writeFileSync(
  path.join(publicDirectory, 'static', 'firebase-config.js'),
  `window.CAMPUS_CLINIC_FIREBASE_CONFIG = ${JSON.stringify(firebaseConfig)};\n`
);
