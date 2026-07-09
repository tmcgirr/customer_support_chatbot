interface ImportMetaEnv {
  readonly VITE_API_BASE?: string;
  readonly VITE_ALLOWED_ORIGINS?: string;
  readonly VITE_PRIVACY_URL?: string;
  readonly VITE_PORTAL_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
