// ใช้ build static/app.css จาก class ใน templates/ และ static/*.js (ดูคำสั่งใน README)
module.exports = {
  content: ["./templates/**/*.html", "./static/*.js"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Prompt", "sans-serif"],
        prompt: ["Prompt", "sans-serif"],
        sarabun: ["Sarabun", "sans-serif"],
        kanit: ["Kanit", "sans-serif"],
      },
    },
  },
  plugins: [require("@tailwindcss/forms"), require("@tailwindcss/container-queries")],
};
