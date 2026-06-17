// basePath параметризован через NEXT_PUBLIC_BASE_PATH (см. lib/base-path.ts):
//   не задан → "/help" (Selectel); "" → поддомен-root; "/help" → явно.
// `?? "/help"` сохраняет дефолт; `|| undefined` превращает "" в «без basePath»
// (Next не принимает пустую строку как basePath).
const basePath = process.env.NEXT_PUBLIC_BASE_PATH ?? "/help";

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  basePath: basePath || undefined,
};

export default nextConfig;
