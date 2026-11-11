import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { LayoutGrid, Box, Wallet, Megaphone, Store, PackagePlus } from "lucide-react";
import { MobileBottomTabBar, type MobileBottomTabVariant } from "./src/components/liquid-glass/MobileBottomTabBar";
import { ThemeProvider, useTheme } from "./src/components/liquid-glass/ThemeProvider";
import "./src/index.css";

const modes = ["fluid", "dock", "super-pill"] as const;
const labels = ["Сводка","Склад","Финансы","Маркетинг","Площадки"];
const tabs = [LayoutGrid,Box,Wallet,Megaphone,Store].map((Icon,i)=>({
  id:String(i),label:labels[i],icon:<Icon size={20} />
}));
const menu = document.querySelector<HTMLDivElement>("main nav")!;
const selected = () => menu.querySelector<HTMLElement>(".on")?.dataset.index ?? "";
function DashboardBar(){
  const {setMode} = useTheme();
  const [tab,setTab] = useState(selected);
  const picker = document.querySelector<HTMLSelectElement>("#glass-mode")!;
  const [variant,setVariant] = useState(picker.value);
  useEffect(()=>{
    setMode("liquid-glass");
    document.documentElement.classList.add("glass-ready");
    const observer = new MutationObserver(()=>setTab(selected()));
    observer.observe(menu,{subtree:true,childList:true,attributes:true,attributeFilter:["class"]});
    const choose=()=>setVariant(picker.value);
    picker.addEventListener("change",choose);
    return ()=>{observer.disconnect();picker.removeEventListener("change",choose)};
  },[]);
  return <MobileBottomTabBar key={variant} className={'dashboard-bar mode-'+variant}
    variant={('ios26-'+variant) as MobileBottomTabVariant} activeTab={tab} tabs={tabs}
    onChange={id=>menu.querySelector<HTMLButtonElement>('[data-index="'+id+'"]')?.click()}
    trailingButton={variant==="super-pill"?{label:"Закупки",icon:<PackagePlus size={21}/>,onClick:()=>window.dispatchEvent(new Event("dashboard-purchases"))}:undefined}/>;
}
const picker = document.querySelector<HTMLSelectElement>("#glass-mode")!;
const mode=new URL(location.href).searchParams.get("glass");
if(modes.some(value=>value===mode))picker.value=mode!;
createRoot(document.getElementById("glass-root")!).render(<ThemeProvider defaultTheme="light"><DashboardBar/></ThemeProvider>);
