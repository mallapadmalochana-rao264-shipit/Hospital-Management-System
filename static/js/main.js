document.addEventListener("DOMContentLoaded", () => {
  // Mobile menu
  const menuBtn = document.getElementById("menuBtn");
  const sidebar = document.getElementById("sidebar");
  if (menuBtn && sidebar) {
    menuBtn.addEventListener("click", () => sidebar.classList.toggle("open"));
    const content = document.querySelector(".content");
    if (content) content.addEventListener("click", () => sidebar.classList.remove("open"));
  }

  // Confirm before deleting
  document.querySelectorAll("form.confirm-delete").forEach((form) => {
    form.addEventListener("submit", (e) => {
      if (!confirm("Delete this record permanently?")) e.preventDefault();
    });
  });

  // Phone fields accept digits only
  document.querySelectorAll('input[type="tel"]').forEach((input) => {
    input.addEventListener("input", () => { input.value = input.value.replace(/\D/g, ""); });
  });

  // Client-side form validation with inline messages
  document.querySelectorAll("form.validate").forEach((form) => {
    form.addEventListener("submit", (e) => {
      let ok = true;
      form.querySelectorAll(".field").forEach((wrap) => {
        const input = wrap.querySelector("input, select, textarea");
        const msg = wrap.querySelector(".error");
        if (!input || !msg) return;
        if (!input.checkValidity()) {
          ok = false;
          msg.textContent = input.validity.patternMismatch && input.title
            ? input.title : input.validationMessage;
          wrap.classList.add("invalid");
        } else {
          msg.textContent = "";
          wrap.classList.remove("invalid");
        }
      });
      if (!ok) {
        e.preventDefault();
        const first = form.querySelector(".invalid");
        if (first) first.scrollIntoView({ behavior: "smooth", block: "center" });
      }
    });
  });

  // Auto-hide flash messages
  setTimeout(() => {
    document.querySelectorAll(".alert").forEach((a) => { a.style.display = "none"; });
  }, 6000);
});
