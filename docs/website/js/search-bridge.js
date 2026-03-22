// Bridge: open shadcn search dialog on Cmd+K / Ctrl+K
document.addEventListener('keydown', function(e) {
    if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        var dialog = document.getElementById('search-dialog');
        if (dialog && typeof dialog.showModal === 'function' && !dialog.open) {
            dialog.showModal();
        }
    }
});
