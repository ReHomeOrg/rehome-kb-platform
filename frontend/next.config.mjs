/** @type {import('next').NextConfig} */
const nextConfig = {
  // #123: standalone output для multi-stage Docker — Next.js собирает
  // self-contained сервер в `.next/standalone/` со всеми нужными
  // node_modules. Runtime image копирует только этот dir (~30-50 MB)
  // вместо full deps (~300+ MB).
  //
  // Не влияет на `next dev` или `next start` (последний всё ещё
  // работает для non-Docker prod). Affects только `next build` output.
  output: "standalone",
};

export default nextConfig;
