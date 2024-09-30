import { Outlet, Link } from "react-router-dom";
import styles from "./Layout.module.css";
import ESB from "../../assets/ESB.svg";
import { CopyRegular } from "@fluentui/react-icons";
import { Dialog, Stack, TextField, Dropdown, IDropdownOption, DropdownMenuItemType, Icon } from "@fluentui/react";
import { useContext, useEffect, useState } from "react";
import { HistoryButton, ShareButton } from "../../components/common/Button";
import { AppStateContext } from "../../state/AppProvider";
import { CosmosDBStatus } from "../../api";
import { IDropdownStyles } from '@fluentui/react/lib/Dropdown';

const Layout = () => {
    const [isSharePanelOpen, setIsSharePanelOpen] = useState<boolean>(false);
    const [copyClicked, setCopyClicked] = useState<boolean>(false);
    const [copyText, setCopyText] = useState<string>("Copy URL");
    const [shareLabel, setShareLabel] = useState<string | undefined>("Share");
    const [hideHistoryLabel, setHideHistoryLabel] = useState<string>("Hide chat history");
    const [showHistoryLabel, setShowHistoryLabel] = useState<string>("Show chat history");
    const [selectedTypes, setSelectedTypes] = useState<string[]>([]);
    const [selectedRules, setSelectedRules] = useState<string[]>([]);
    const [selectedParts, setSelectedParts] = useState<string[]>([]);
    const appStateContext = useContext(AppStateContext)
    const ui = appStateContext?.state.frontendSettings?.ui;

    const handleShareClick = () => {
        setIsSharePanelOpen(true);
    };

    const handleSharePanelDismiss = () => {
        setIsSharePanelOpen(false);
        setCopyClicked(false);
        setCopyText("Copy URL");
    };

    const handleCopyClick = () => {
        navigator.clipboard.writeText(window.location.href);
        setCopyClicked(true);
    };

    const handleHistoryClick = () => {
        appStateContext?.dispatch({ type: 'TOGGLE_CHAT_HISTORY' })
    };

    useEffect(() => {
        if (copyClicked) {
            setCopyText("Copied URL");
        }
    }, [copyClicked]);

    useEffect(() => { }, [appStateContext?.state.isCosmosDBAvailable.status]);

    useEffect(() => {
        const handleResize = () => {
          if (window.innerWidth < 480) {
            setShareLabel(undefined)
            setHideHistoryLabel("Hide history")
            setShowHistoryLabel("Show history")
          } else {
            setShareLabel("Share")
            setHideHistoryLabel("Hide chat history")
            setShowHistoryLabel("Show chat history")
          }
        };
    
        window.addEventListener('resize', handleResize);
        handleResize();
    
        return () => window.removeEventListener('resize', handleResize);
      }, []);  

    const typeDropdownOptions = [
        { key: 'Code', text: 'Code' },
        { key: 'Agreed Procedure', text: 'Agreed Procedure' },
        { key: 'Appendice', text: 'Appendix' },
        { key: 'Glossary', text: 'Glossary' },
        { key: 'Training Materials', text: 'Training Materials' },
    ];
    
    const rulesDropdownOptions = [
        { key: 'Trading Settlement Code', text: 'Trading Settlement Code' },
        { key: 'Capacity Market Rules', text: 'Capacity Market Rules' }
    ];
    
    const partsDropdownOptions = [
        { key: 'A', text: 'Part A' },
        { key: 'B', text: 'Part B' },
        { key: 'C', text: 'Part C' }
    ];     

    // Define the combined options array with headers and dividers
    const combinedOptions: IDropdownOption[] = [
        { key: 'typesHeader', text: 'Document Type', itemType: DropdownMenuItemType.Header },
        ...typeDropdownOptions,
        { key: 'divider_1', text: '-', itemType: DropdownMenuItemType.Divider },
        { key: 'rulesHeader', text: 'Rules Set', itemType: DropdownMenuItemType.Header },
        ...rulesDropdownOptions,
        { key: 'divider_2', text: '-', itemType: DropdownMenuItemType.Divider },
        { key: 'partsHeader', text: 'Trading Settlement Code Part', itemType: DropdownMenuItemType.Header },
        ...partsDropdownOptions,
    ];

    // Define the combined onDropdownChange handler
    const onDropdownChange = (
        event: React.FormEvent,
        option?: IDropdownOption,
        index?: number
    ): void => {
        if (option) {
            // Determine the category of the selected option and update the corresponding state
            if (typeDropdownOptions.some(opt => opt.key === option.key)) {
                const newSelectedTypes  = option.selected
                    ? [...selectedTypes, option.key as string]
                    : selectedTypes.filter(key => key !== option.key);
                setSelectedTypes(newSelectedTypes);
                appStateContext?.dispatch({
                    type: 'UPDATE_SELECTED_TYPES',
                    payload: newSelectedTypes,
                });
            }
            if (rulesDropdownOptions.some(opt => opt.key === option.key)) {
                const newSelectedRules = option.selected
                    ? [...selectedRules, option.key as string]
                    : selectedRules.filter(key => key !== option.key);
                setSelectedRules(newSelectedRules);
                appStateContext?.dispatch({
                    type: 'UPDATE_SELECTED_RULES',
                    payload: newSelectedRules,
                });
            }
            if (partsDropdownOptions.some(opt => opt.key === option.key)) {
                const newSelectedParts = option.selected
                    ? [...selectedParts, option.key as string]
                    : selectedParts.filter(key => key !== option.key);
                setSelectedParts(newSelectedParts);
                appStateContext?.dispatch({
                    type: 'UPDATE_SELECTED_PARTS',
                    payload: newSelectedParts,
                });
            }
        }
    };

    const dropdownStyles: Partial<IDropdownStyles> = {
        dropdown: { width: 250,
        },
    };

    // Handler for clearing the selection
    const onClearSelection = () => {
        setSelectedTypes([]);
        setSelectedRules([]);
        setSelectedParts([]);
        // Dispatch an action or call a function to update the app state if necessary
          // Dispatch actions to update the app state context for each category
        appStateContext?.dispatch({
            type: 'UPDATE_SELECTED_TYPES',
            payload: [],
        });
        appStateContext?.dispatch({
            type: 'UPDATE_SELECTED_RULES',
            payload: [],
        });
        appStateContext?.dispatch({
            type: 'UPDATE_SELECTED_PARTS',
            payload: [],
        });
    };

    // Custom render function for the caret down icon and clear button
    const onRenderCaretDown = () => {
        const anySelected = selectedTypes.length > 0 || selectedRules.length > 0 || selectedParts.length > 0;

        return (
        <Stack horizontal verticalAlign="center">
            
            {anySelected  && (
            <Icon
                iconName="Cancel"
                onClick={onClearSelection}
                styles={{
                root: {
                    marginRight: '8px',
                    cursor: 'pointer',
                    color: 'rgb(96, 94, 92)',
                    backgroundColor: 'white',
                    // Add any additional styles you need
                }
                }}
            />
            )}
            <Icon iconName="ChevronDown" styles={{ root: { color: 'rgb(96, 94, 92)' } }} />
        </Stack>
        );
    };

    const allSelectedKeys = [...selectedTypes, ...selectedRules, ...selectedParts];

    return (
        <div className={styles.layout}>
            <header className={styles.header} role={"banner"}>
                <Stack horizontal verticalAlign="center" horizontalAlign="space-between">
                    <Stack horizontal verticalAlign="center">
                        <img
                            src={ui?.logo ? ui.logo : ESB}
                            className={styles.headerIcon}
                            aria-hidden="true"
                        />
                        <Link to="/" className={styles.headerTitleContainer}>
                            <h1 className={styles.headerTitle}>{ui?.title}</h1>
                        </Link>
                    </Stack>
                    <Stack horizontal tokens={{ childrenGap: 10 }} className={styles.shareButtonContainer}>
                        <Dropdown
                            placeholder="Filter documents"
                            multiSelect
                            options={combinedOptions}
                            onChange={onDropdownChange}
                            selectedKeys={allSelectedKeys}
                            styles={dropdownStyles}
                            onRenderCaretDown={onRenderCaretDown}
                        />
                        {(appStateContext?.state.isCosmosDBAvailable?.status !== CosmosDBStatus.NotConfigured) &&
                            <HistoryButton onClick={handleHistoryClick} text={appStateContext?.state?.isChatHistoryOpen ? hideHistoryLabel : showHistoryLabel} />
                        }
                        {ui?.show_share_button &&<ShareButton onClick={handleShareClick} text={shareLabel} />}
                    </Stack>
                </Stack>
            </header>
            <Outlet />
            <Dialog
                onDismiss={handleSharePanelDismiss}
                hidden={!isSharePanelOpen}
                styles={{

                    main: [{
                        selectors: {
                            ['@media (min-width: 480px)']: {
                                maxWidth: '600px',
                                background: "#FFFFFF",
                                boxShadow: "0px 14px 28.8px rgba(0, 0, 0, 0.24), 0px 0px 8px rgba(0, 0, 0, 0.2)",
                                borderRadius: "8px",
                                maxHeight: '200px',
                                minHeight: '100px',
                            }
                        }
                    }]
                }}
                dialogContentProps={{
                    title: "Share the web app",
                    showCloseButton: true
                }}
            >
                <Stack horizontal verticalAlign="center" style={{ gap: "8px" }}>
                    <TextField className={styles.urlTextBox} defaultValue={window.location.href} readOnly />
                    <div
                        className={styles.copyButtonContainer}
                        role="button"
                        tabIndex={0}
                        aria-label="Copy"
                        onClick={handleCopyClick}
                        onKeyDown={e => e.key === "Enter" || e.key === " " ? handleCopyClick() : null}
                    >
                        <CopyRegular className={styles.copyButton} />
                        <span className={styles.copyButtonText}>{copyText}</span>
                    </div>
                </Stack>
            </Dialog>
        </div>
    );
};

export default Layout;
