// PMP Quiz - Main JS

// Auto-dismiss flash messages after 5 seconds
document.addEventListener('DOMContentLoaded', function() {
    document.querySelectorAll('.flash').forEach(el => {
        setTimeout(() => {
            el.style.opacity = '0';
            el.style.transition = 'opacity 0.5s';
            setTimeout(() => el.remove(), 500);
        }, 5000);
    });
});

// Close mobile menu on link click
document.querySelectorAll('.navbar-nav a').forEach(a => {
    a.addEventListener('click', () => {
        document.querySelector('.navbar-nav').classList.remove('open');
    });
});
