import { motion } from "framer-motion";

export function TypingIndicator() {
  return (
    <motion.div className="typing" role="status" aria-label="Assistant is typing"
      initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
      {[0, 1, 2].map((i) => (
        <motion.i key={i} animate={{ opacity: [0.25, 1, 0.25], y: [0, -3, 0] }}
          transition={{ duration: 1.1, repeat: Infinity, delay: i * 0.16, ease: "easeInOut" }} />
      ))}
    </motion.div>
  );
}
