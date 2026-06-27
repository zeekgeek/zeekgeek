import { createApp } from './app.js';
import { config, tokenConfigured } from './config.js';

const app = createApp();

const server = app.listen(config.port, () => {
  const url = `http://localhost:${config.port}`;
  console.log('');
  console.log(`  ${config.assistantName} voice automation hub is running.`);
  console.log(`  Dashboard:  ${url}`);
  console.log(`  Health:     ${url}/api/health`);
  console.log(`  Command:    POST ${url}/api/command  { "text": "what time is it" }`);
  console.log('');
  if (!tokenConfigured()) {
    console.warn('  ⚠  No ACCESS_TOKEN set — the API is OPEN. Set one in .env before exposing this to the internet.');
    console.log('');
  }
});

function shutdown(signal) {
  console.log(`\nReceived ${signal}, shutting down.`);
  server.close(() => process.exit(0));
}
process.on('SIGINT', () => shutdown('SIGINT'));
process.on('SIGTERM', () => shutdown('SIGTERM'));
