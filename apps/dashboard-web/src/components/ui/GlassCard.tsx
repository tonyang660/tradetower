import type { ReactNode } from "react";
import clsx from "clsx";
import { motion } from "framer-motion";

export default function GlassCard({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.28 }}
      className={clsx(
        "rounded-[28px] border border-white/10 bg-white/6 p-5 shadow-glass backdrop-blur-xl",
        className
      )}
    >
      {children}
    </motion.div>
  );
}
