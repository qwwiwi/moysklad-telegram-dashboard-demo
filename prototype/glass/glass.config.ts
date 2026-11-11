import {defineConfig} from "vite";
import react from "@vitejs/plugin-react";
import tailwind from "@tailwindcss/vite";
export default defineConfig({define:{"process.env.NODE_ENV":JSON.stringify("production")},plugins:[react(),tailwind()],build:{outDir:"build-dashboard",lib:{entry:"dashboard.tsx",name:"DashboardGlass",formats:["iife"],fileName:()=>"dock.js",cssFileName:"dock"}}});
