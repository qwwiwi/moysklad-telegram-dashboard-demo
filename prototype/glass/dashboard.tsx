import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { LayoutGrid, Box, Wallet, Megaphone, Store } from "lucide-react";
import { MobileBottomTabBar } from "./src/components/liquid-glass/MobileBottomTabBar";
import { ThemeProvider, useTheme } from "./src/components/liquid-glass/ThemeProvider";
import "./src/index.css";

const labels = ["Сводка","Склад","Финансы","Маркетинг","Площадки"];
const tabs = [LayoutGrid,Box,Wallet,Megaphone,Store].map((Icon,i)=>({
  id:String(i),label:labels[i],icon:<Icon size={20} />
}));
const menu = document.querySelector<HTMLDivElement>("main nav")!;
const selected = () => menu.querySelector<HTMLElement>(".on")?.dataset.index ?? "";
function DashboardBar(){
  const {setMode, theme, setTheme} = useTheme();
  useEffect(()=>{
    const button=document.getElementById("brand-toggle")!;
    button.setAttribute("aria-pressed",String(theme==="dark"));
    const toggle=()=>setTheme(theme==="dark"?"light":"dark");
    button.addEventListener("click",toggle);
    return ()=>button.removeEventListener("click",toggle);
  },[theme,setTheme]);
  const [tab,setTab] = useState(selected);

  useEffect(()=>{
    setMode("liquid-glass");
    document.documentElement.classList.add("glass-ready");
    const observer = new MutationObserver(()=>setTab(selected()));
    observer.observe(menu,{subtree:true,childList:true,attributes:true,attributeFilter:["class"]});
    return ()=>observer.disconnect();
  },[]);
  return <MobileBottomTabBar className="dashboard-bar mode-fluid"
    variant="ios26-fluid" activeTab={tab} tabs={tabs}
    onChange={id=>menu.querySelector<HTMLButtonElement>('[data-index="'+id+'"]')?.click()}/>;
}
createRoot(document.getElementById("glass-root")!).render(<ThemeProvider defaultTheme="light"><DashboardBar/></ThemeProvider>);
