/**
 * Sonar Battleship — page behaviour
 * Minimal, dependency-free replacement for the template's main.js
 * (mobile nav, scroll-top button, scroll reveals, hash scrolling).
 */
(function () {
  "use strict";

  /* Mobile nav toggle */
  var toggleBtn = document.querySelector(".nav-toggle");
  var nav = document.getElementById("nav");

  function closeNav() {
    if (nav) nav.classList.remove("is-open");
    if (toggleBtn) toggleBtn.setAttribute("aria-expanded", "false");
    var icon = toggleBtn ? toggleBtn.querySelector("i") : null;
    if (icon) {
      icon.classList.add("bi-list");
      icon.classList.remove("bi-x-lg");
    }
  }

  var toggleIcon = toggleBtn ? toggleBtn.querySelector("i") : null;

  if (toggleBtn && nav) {
    toggleBtn.addEventListener("click", function () {
      var isOpen = nav.classList.toggle("is-open");
      toggleBtn.setAttribute("aria-expanded", isOpen ? "true" : "false");
      if (toggleIcon) {
        toggleIcon.classList.toggle("bi-list", !isOpen);
        toggleIcon.classList.toggle("bi-x-lg", isOpen);
      }
    });

    nav.querySelectorAll("a").forEach(function (link) {
      link.addEventListener("click", closeNav);
    });
  }

  /* Scroll-top button */
  var scrollTopBtn = document.querySelector(".scroll-top");
  function toggleScrollTop() {
    if (!scrollTopBtn) return;
    if (window.scrollY > 300) {
      scrollTopBtn.classList.add("active");
    } else {
      scrollTopBtn.classList.remove("active");
    }
  }
  if (scrollTopBtn) {
    scrollTopBtn.addEventListener("click", function (e) {
      e.preventDefault();
      window.scrollTo({ top: 0, behavior: "smooth" });
    });
    window.addEventListener("scroll", toggleScrollTop);
    toggleScrollTop();
  }

  /* Sticky header shadow on scroll */
  var header = document.querySelector(".site-header");
  function toggleHeaderState() {
    if (!header) return;
    header.classList.toggle("is-scrolled", window.scrollY > 20);
  }
  window.addEventListener("scroll", toggleHeaderState);
  toggleHeaderState();

  /* Lightweight scroll-reveal for [data-reveal] elements.
     Content is visible by default (see CSS); we only switch on the
     hidden/animate-in state once the observer that reveals it again
     is confirmed to exist, so a script error can't hide real content. */
  if ("IntersectionObserver" in window) {
    var revealTargets = document.querySelectorAll("[data-reveal]");
    if (revealTargets.length) {
      document.documentElement.classList.add("js-reveal");
      var io = new IntersectionObserver(
        function (entries) {
          entries.forEach(function (entry) {
            if (entry.isIntersecting) {
              entry.target.classList.add("is-visible");
              io.unobserve(entry.target);
            }
          });
        },
        { threshold: 0.15, rootMargin: "0px 0px -40px 0px" }
      );
      revealTargets.forEach(function (el) { io.observe(el); });
    }
  }
})();
