from pathlib import Path
import unittest


class ClientLayoutRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = Path(__file__).with_name("client.js").read_text(encoding="utf-8")

    def test_microsoft_sessions_live_in_more_menu_not_toolbar(self) -> None:
        more_menu = self.client.split("function openExplorerMoreMenu(trigger) {", 1)[1].split("function explorerToolbarButton", 1)[0]
        self.assertIn('"Microsoft web sessions"', more_menu)
        self.assertIn('new CustomEvent("plexpoint:open-microsoft-sessions")', more_menu)
        self.assertTrue('document.addEventListener("plexpoint:open-microsoft-sessions", () => void showMicrosoftSessions())' in self.client)
        self.assertFalse('function ensureSessionsButton' in self.client)

    def test_details_rows_have_matching_horizontal_insets(self) -> None:
        self.assertIn("plexpoint-v180-symmetric-list-inset-style", self.client)
        self.assertIn("padding-left: 8px !important", self.client)
        self.assertIn("padding-right: 8px !important", self.client)

    def test_short_desktop_windows_do_not_keep_the_full_height_row_offset(self) -> None:
        self.assertIn("plexpoint-v185-compact-height-listing-style", self.client)
        self.assertIn(
            "@media (min-width: 769px) and (max-height: 720px)",
            self.client,
        )
        self.assertIn(
            ".listing-view-root > .listing-items {\n"
            "          padding-top: 0 !important;",
            self.client,
        )

    def test_more_menu_has_account_backed_hidden_items_toggle(self) -> None:
        self.assertIn('"Hidden items"', self.client)
        self.assertIn('which: ["showHidden"]', self.client)
        self.assertIn('data: { showHidden: requested }', self.client)
        self.assertIn('hiddenItemsButton.setAttribute("role", "menuitemcheckbox")', self.client)
        self.assertIn('hiddenItemsButton.setAttribute("aria-checked"', self.client)
        self.assertIn("requestSoftListingReload()", self.client)

    def test_hidden_rows_override_the_details_grid_display(self) -> None:
        self.assertIn(
            "html body.plexpoint-explorer-layout\n"
            "      .listing-view-root .listing-items\n"
            "      :is(.folder-items, .file-items)\n"
            "      > .listing-item.plexpoint-hidden-item",
            self.client,
        )
        self.assertIn("display: none !important", self.client)

    def test_hidden_rows_are_concealed_until_the_route_manifest_is_ready(self) -> None:
        self.assertIn("html.plexpoint-hidden-scan-pending", self.client)
        self.assertIn(
            'document.documentElement.classList.add("plexpoint-hidden-scan-pending")',
            self.client,
        )
        self.assertIn(
            'document.documentElement.classList.remove("plexpoint-hidden-scan-pending")',
            self.client,
        )
        self.assertIn("const observedRouteKey = routeKey(currentRoute())", self.client)

    def test_sidebar_tree_uses_hidden_manifest_and_account_toggle(self) -> None:
        self.assertIn("plexpoint-sidebar-hidden-entry", self.client)
        self.assertIn("plexpoint-sidebar-hidden-pending", self.client)
        self.assertIn("plexpoint-show-hidden-items", self.client)
        self.assertIn("hidden: new Set(", self.client)
        self.assertIn("const hidden = manifest.hidden.has(name)", self.client)
        self.assertIn('window.addEventListener("plexpoint:hidden-items-changed"', self.client)

    def test_file_viewer_hides_the_empty_top_shelf(self) -> None:
        self.assertIn("plexpoint-v164-file-view-toolbar-style", self.client)
        self.assertIn(
            "html body.${ACTIVE_CLASS}.plexpoint-explorer-layout #main > #shelf",
            self.client,
        )
        self.assertIn("#markedown-viewer, #previewer, #editor-container", self.client)
        self.assertIn(".viewer-background, .threejs-viewer", self.client)
        self.assertIn("function syncFileViewContentTop()", self.client)
        self.assertIn(
            "top: var(--plexpoint-explorer-content-top, var(--header-height, 4em)) !important;",
            self.client,
        )
        self.assertIn("padding-top: 0 !important;", self.client)

    def test_office_editors_do_not_keep_the_preview_header_gap(self) -> None:
        self.assertIn("plexpoint-office-file-view-active", self.client)
        self.assertIn('main.querySelector("iframe[name=\'frameEditor\']")', self.client)
        self.assertIn(
            "html body.${ACTIVE_CLASS}.${OFFICE_ACTIVE_CLASS}.plexpoint-explorer-layout #main",
            self.client,
        )
        self.assertIn("top: 0 !important;", self.client)

    def test_microsoft_save_back_closes_all_backdrops_and_uses_shared_toast(self) -> None:
        self.assertIn(
            'document.querySelectorAll(".plexpoint-ms-overlay").forEach((overlay) => overlay.remove())',
            self.client,
        )

    def test_microsoft_cleanup_remains_visible_and_separate_from_save(self) -> None:
        self.assertIn('if (!result.cloudRemoved) showSession(target, result)', self.client)
        self.assertIn('"Retry cloud cleanup"', self.client)
        self.assertIn('saveBack(target, cleanup, false, true)', self.client)
        self.assertIn('path: target.path, force, cleanupOnly', self.client)
        self.assertIn('showSession(target, { ...status.active, app: target.app })', self.client)
        self.assertIn('for the web copy is ready', self.client)
        self.assertNotIn('for the web is open`', self.client)

    def test_microsoft_context_actions_close_filebrowser_prompt_state(self) -> None:
        self.assertIn("function dismissNativeContextMenu(menu)", self.client)
        self.assertIn('const overlay = document.querySelector(".overlay")', self.client)
        self.assertIn("overlay.click();", self.client)
        self.assertTrue("dismissNativeContextMenu(menu);\n      if (target.help) showFormatHelp(target);\n      else void openTarget(target, popup);" in self.client)
        self.assertIn(
            "dismissNativeContextMenu(menu);\n        showSession(target, { ...status.active, app: target.app });",
            self.client,
        )

    def test_right_click_menu_keeps_its_dismiss_overlay_but_does_not_dim(self) -> None:
        self.assertIn("Plexpoint Explorer V186 — UNDIMMED RIGHT-CLICK MENUS", self.client)
        self.assertIn('const OPEN_CLASS = "plexpoint-context-menu-open"', self.client)
        self.assertIn('document.getElementById("context-menu") instanceof HTMLElement', self.client)
        self.assertIn(
            "body.plexpoint-explorer-layout.plexpoint-context-menu-open #app .overlay {\n"
            "        background: transparent !important;",
            self.client,
        )
        self.assertIn("new MutationObserver(syncContextMenuOverlay).observe(document.body", self.client)
        self.assertIn('new CustomEvent("plexpoint:toast"', self.client)
        self.assertIn('document.addEventListener("plexpoint:toast"', self.client)
        self.assertIn(
            'closeDialog();\n      document.querySelector(".plexpoint-ms-session")?.remove();\n'
            '      if (!result.cloudRemoved) showSession(target, result);\n'
            '      toast(result.message || "Saved back to FilePoint.", 6000);',
            self.client,
        )

    def test_document_viewer_back_returns_to_parent_folder(self) -> None:
        self.assertIn("Plexpoint Explorer V184 — DOCUMENT VIEWER BACK RETURNS TO PARENT", self.client)
        self.assertIn("function fileParentPath(pathname)", self.client)
        self.assertIn("history.pushState = function plexpointViewerPushState", self.client)
        self.assertIn("const result = history.replaceState(...args)", self.client)
        self.assertIn('window.addEventListener("popstate", handleViewerPopstate)', self.client)
        self.assertIn("window.location.replace(parent)", self.client)

    def test_closing_a_document_does_not_leave_it_next_in_back_history(self) -> None:
        self.assertIn("const isViewerCloseToParent =", self.client)
        self.assertIn("let pendingViewerCloseParent = \"\"", self.client)
        self.assertIn("function rememberViewerClose(event)", self.client)
        self.assertIn("function closeViewerViaHistory(event)", self.client)
        self.assertIn('target?.closest(".floating-close")', self.client)
        self.assertIn('document.addEventListener("pointerdown", rememberViewerClose, true)', self.client)
        self.assertIn('document.addEventListener("click", closeViewerViaHistory, true)', self.client)
        self.assertIn("event.stopImmediatePropagation()", self.client)
        self.assertIn("window.history.back()", self.client)
        self.assertIn(
            "normalizedPath(next.pathname) === normalizedPath(closingParent)",
            self.client,
        )
        self.assertIn("Replace the file slot instead.", self.client)

    def test_toolbar_back_and_forward_use_native_browser_history(self) -> None:
        self.assertIn("function explorerHistoryGo(delta)", self.client)
        self.assertIn("window.history.back()", self.client)
        self.assertIn("window.history.forward()", self.client)
        self.assertNotIn('typeof router.go === "function"', self.client)

    def test_dragging_a_listing_item_uses_the_existing_move_api(self) -> None:
        self.assertIn("V188 — DRAG FILES AND FOLDERS ONTO A FOLDER TO MOVE THEM", self.client)
        self.assertIn('const FILE_MOVE_DRAG_MIME = "application/x-plexpoint-resource-move"', self.client)
        self.assertIn('document.addEventListener("dragstart", (event) => {', self.client)
        self.assertIn('const row = event.target.closest(".listing-view-root .listing-item[data-name]")', self.client)
        self.assertIn('row.draggable = true', self.client)
        self.assertIn('row.querySelector(`:scope > .plexpoint-file-move-handle`)?.remove()', self.client)
        self.assertIn('event.dataTransfer.effectAllowed = "move"', self.client)
        self.assertIn('function fileMoveDragPreview()', self.client)
        self.assertIn('void performFileBrowserMoveCopy(items, "move", { overwrite: false })', self.client)

    def test_drag_move_rejects_a_folder_being_dropped_into_itself_or_a_child(self) -> None:
        self.assertIn("function canDropFileMove(items, destination)", self.client)
        self.assertIn('destinationPath !== from && !destinationPath.startsWith(`${from}/`)', self.client)
        self.assertIn('row.classList.add(FILE_MOVE_DRAG_TARGET_CLASS)', self.client)
        self.assertIn('target.row.dataset.plexpointFileMoveLabel', self.client)
        self.assertIn('showToast(`Moved ${count} ${noun} to ${target.destination.name}.`, 4200)', self.client)

    def test_recycle_bin_and_real_undo_redo_controls_exist(self) -> None:
        self.assertIn('button.id = "plexpoint-recycle-bin-link"', self.client)
        self.assertIn('fetch("/__foldericons/recycle-bin"', self.client)
        self.assertIn('fetch("/__foldericons/history"', self.client)
        self.assertIn('window.addEventListener("keydown", interceptExplorerHistoryShortcut, true)', self.client)
        self.assertIn('void applyExplorerHistoryAction("undo")', self.client)
        self.assertIn('void applyExplorerHistoryAction("redo")', self.client)

    def test_recycle_bin_is_a_bottom_tree_row_with_windows_icons(self) -> None:
        self.assertIn('treeItem.className = "tree-item plexpoint-recycle-bin-tree-item"', self.client)
        self.assertIn('button.classList.add("plexpoint-recycle-bin-tree-node")', self.client)
        self.assertIn('sidebar.querySelector(".file-tree-root > .tree-list")', self.client)
        self.assertIn("destination.lastElementChild !== treeItem", self.client)
        self.assertIn("destination.appendChild(treeItem)", self.client)
        self.assertIn('"/__foldericons/recycle-bin-icon?state=empty"', self.client)
        self.assertIn('const binState = count > 0 ? "full" : "empty"', self.client)
        self.assertNotIn("host.prepend(button)", self.client)

    def test_links_sidebar_uses_material_recycle_icon_but_navigation_keeps_bin_art(self) -> None:
        self.assertIn('plexpoint-recycle-home-icon', self.client)
        self.assertIn('homeIcon.textContent = "delete"', self.client)
        self.assertIn('function recycleBinUsesSidebarLinksIcon(sidebar)', self.client)
        self.assertIn('sidebar.querySelector(".file-tree-root > .tree-list")', self.client)
        self.assertIn('const linksIcon = recycleBinUsesSidebarLinksIcon(sidebar)', self.client)
        self.assertIn('if (button.dataset.plexpointLinksIcon !== linksIcon)', self.client)
        self.assertIn('data-plexpoint-links-icon="true"', self.client)
        self.assertIn('color: var(--primaryColor, #2196f3) !important', self.client)

    def test_recycle_bin_opens_as_a_normal_details_folder_not_a_dialog(self) -> None:
        self.assertIn('view.id = "plexpoint-recycle-bin-folder-view"', self.client)
        self.assertIn('view.className = "listing-items list"', self.client)
        self.assertIn('document.body.classList.add("plexpoint-recycle-folder-active")', self.client)
        self.assertIn('modified.textContent = "Date deleted"', self.client)
        self.assertIn('type.className = "plexpoint-type-cell"', self.client)
        self.assertIn('window.history.pushState(historyState, "", url)', self.client)
        self.assertIn('label: "Restore selected"', self.client)
        self.assertIn('label: "Empty Recycle Bin"', self.client)
        self.assertNotIn("openRecycleBinDialog", self.client)
        self.assertNotIn("plexpoint-recycle-bin-overlay", self.client)
        self.assertNotIn('id = "plexpoint-recycle-bin-dialog"', self.client)

    def test_empty_recycle_bin_does_not_add_an_opaque_scroll_panel(self) -> None:
        recycle_view_style = """#plexpoint-recycle-bin-folder-view {
        width: 100% !important; min-width: 0 !important; min-height: 0 !important;
        height: auto !important; flex: 0 0 auto !important;
        margin: 0 !important; padding: 0 !important; box-sizing: border-box !important;
        color: var(--plexpoint-explorer-text, #f2f5f6) !important;
        background: transparent !important;
        overflow: visible !important;
      }"""
        self.assertIn(recycle_view_style, self.client)

    def test_multi_selection_menu_restores_bulk_safe_actions(self) -> None:
        self.assertIn("function ensureMultiSelectionMenuActions(menu)", self.client)
        self.assertIn('createMenuAction("Copy Path", "link"', self.client)
        self.assertIn('createMenuAction("Properties", "info"', self.client)
        self.assertIn("function openMultiItemProperties(items)", self.client)
        self.assertIn("function saveMultiPropertiesHidden(prompt, items)", self.client)
        self.assertIn("if (selectedRows.length > 1) return", self.client)
        self.assertIn(
            '#context-menu:not([data-plexpoint-context-menu-stable="true"])',
            self.client,
        )
        self.assertIn(
            'menu.dataset.plexpointContextMenuStable = "true"',
            self.client,
        )
        self.assertIn(
            "A newly mounted context menu must be completed in this mutation",
            self.client,
        )

    def test_alt_enter_opens_selected_item_properties(self) -> None:
        self.assertIn("function interceptWindowsPropertiesShortcut(event)", self.client)
        self.assertIn('event.key !== "Enter"', self.client)
        self.assertIn("!event.altKey", self.client)
        self.assertIn(
            'window.addEventListener("keydown", interceptWindowsPropertiesShortcut, true)',
            self.client,
        )
        self.assertIn("openSyntheticItemInfo(items[0])", self.client)
        self.assertIn("openMultiItemProperties(items)", self.client)

    def test_explorer_search_has_full_results_view_and_keyboard_shortcuts(self) -> None:
        self.assertIn('searchInput.id = "plexpoint-explorer-search-input"', self.client)
        self.assertIn('view.id = "plexpoint-search-results"', self.client)
        self.assertIn('`/__foldericons/search?${params}`', self.client)
        self.assertIn('`/api/tools/search?${params}`', self.client)
        self.assertIn('key === "e" || key === "f"', self.client)
        self.assertIn('key === "f3"', self.client)
        self.assertIn('resultStatus.setAttribute("role", "status")', self.client)
        self.assertNotIn('scope.setAttribute("aria-label", "Search scope")', self.client)
        self.assertIn("searchRecursive: true", self.client)
        self.assertIn("view.append(header, resultStatus)", self.client)

    def test_explorer_search_offers_columns_without_example_filter_bar(self) -> None:
        self.assertNotIn('tips.className = "plexpoint-search-tips"', self.client)
        self.assertIn('["location", "Location"]', self.client)
        self.assertIn('["modified", "Date modified"]', self.client)
        self.assertIn('["type", "Type"]', self.client)
        self.assertIn('["size", "Size"]', self.client)
        self.assertIn("searchInput.value = state.searchQuery", self.client)

    def test_mobile_shell_has_a_dedicated_two_row_layout(self) -> None:
        self.assertIn("Plexpoint Explorer V182 — MOBILE-FIRST APPLICATION SHELL", self.client)
        self.assertIn('--plexpoint-mobile-shell-height', self.client)
        self.assertIn('grid-template-columns: 48px minmax(0, 1fr) !important', self.client)
        self.assertIn('grid-row: 2 !important', self.client)
        self.assertIn('header.flexbar > #plexpoint-explorer-toolbar', self.client)
        self.assertIn('body.plexpoint-explorer-layout #shelf', self.client)
        self.assertIn('body.plexpoint-explorer-layout #status-bar', self.client)

    def test_mobile_rows_and_home_cards_are_touch_sized(self) -> None:
        self.assertIn('grid-template-columns: 48px minmax(0, 1fr) !important', self.client)
        self.assertIn('min-height: 72px !important', self.client)
        self.assertIn('grid-template-columns: repeat(2, minmax(0, 1fr)) !important', self.client)
        self.assertIn('grid-template-rows: 48px minmax(28px, auto) !important', self.client)
        self.assertIn('min-height: 126px !important', self.client)
        self.assertIn('.plexpoint-reorder-button', self.client)

    def test_mobile_content_has_matching_left_and_right_insets(self) -> None:
        self.assertIn('calc(8px + var(--safe-area-right, 0px))', self.client)
        self.assertIn('calc(8px + var(--safe-area-left, 0px))', self.client)
        self.assertIn('html.plexpoint-transparent-effects\n          body.plexpoint-explorer-layout #main', self.client)

    def test_home_cards_open_only_on_a_double_click(self) -> None:
        self.assertIn('homeLastCardClick: null', self.client)
        self.assertIn('const isDoubleClick =', self.client)
        self.assertIn('event.detail >= 2', self.client)
        self.assertIn('priorClick?.card === nav.card', self.client)
        self.assertIn('state.homeLastCardClick = { card: nav.card, at: now }', self.client)
        self.assertIn('window.addEventListener("dblclick", (event) => {', self.client)
        self.assertIn('event.target.closest(".plexpoint-home-card")', self.client)

    def test_mobile_drawer_and_context_menu_have_stable_layering(self) -> None:
        self.assertIn('styleAuthorityObserver.observe(document.head, { childList: true })', self.client)
        self.assertIn('queueMicrotask(promoteMobileStyle)', self.client)
        self.assertIn('body.plexpoint-explorer-layout #context-menu.centered', self.client)
        self.assertIn('z-index: 2147483007 !important', self.client)
        self.assertIn('transition: none !important', self.client)

    def test_mobile_search_expands_and_results_collapse_to_cards(self) -> None:
        self.assertIn('#plexpoint-explorer-search:focus-within', self.client)
        self.assertIn('#plexpoint-search-results .plexpoint-search-table-header', self.client)
        self.assertIn('#plexpoint-search-results .plexpoint-search-result-row', self.client)
        self.assertIn('max-height: min(68dvh, 520px) !important', self.client)


if __name__ == "__main__":
    unittest.main()
