// Abre e fecha o menu em telas pequenas (substitui o antigo onclick inline, bloqueado pela CSP).
document.querySelectorAll("[data-menu-toggle]").forEach((button) => {
  button.addEventListener("click", () => {
    const open = document.querySelector(".nav").classList.toggle("open");
    button.setAttribute("aria-expanded", String(open));
  });
});
