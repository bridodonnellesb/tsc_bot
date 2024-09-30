import { Outlet, Link } from "react-router-dom";
import styles from "./Layout.module.css";
import ESB from "../../assets/ESB.svg";
import { CopyRegular } from "@fluentui/react-icons";
import { Dialog, Stack, TextField, Dropdown, IDropdownOption, DropdownMenuItemType } from "@fluentui/react";
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

    // const onTypesDropdownChange = (
    //     event: React.FormEvent<HTMLDivElement>,
    //     option?: IDropdownOption, // option is now optional and matches IDropdownOption type
    //     index?: number // index is optional and of type number
    // ): void => {
    //     if (option) {
    //         const newSelectedTypes = option.selected
    //             ? [...selectedTypes, option.key as string]
    //             : selectedTypes.filter(key => key !== option.key);

    //         // Update the local state
    //         setSelectedTypes(newSelectedTypes);

    //         // Dispatch the action to update the AppStateContext
    //         appStateContext?.dispatch({
    //             type: 'UPDATE_SELECTED_TYPES',
    //             payload: newSelectedTypes,
    //         });
    //     }
    // };
    
    // const onRulesDropdownChange = (
    //     event: React.FormEvent<HTMLDivElement>,
    //     option?: IDropdownOption, // option is now optional and matches IDropdownOption type
    //     index?: number // index is optional and of type number
    // ): void => {
    //     if (option) {
    //         const newSelectedRules = option.selected
    //             ? [...selectedRules, option.key as string]
    //             : selectedRules.filter(key => key !== option.key);

    //         // Update the local state
    //         setSelectedRules(newSelectedRules);

    //         // Dispatch the action to update the AppStateContext
    //         appStateContext?.dispatch({
    //             type: 'UPDATE_SELECTED_RULES',
    //             payload: newSelectedRules,
    //         });
    //     }
    // };

    // const onPartsDropdownChange = (
    //     event: React.FormEvent<HTMLDivElement>,
    //     option?: IDropdownOption, // option is now optional and matches IDropdownOption type
    //     index?: number // index is optional and of type number
    // ): void => {
    //     if (option) {
    //         const newSelectedParts = option.selected
    //             ? [...selectedParts, option.key as string]
    //             : selectedParts.filter(key => key !== option.key);

    //         // Update the local state
    //         setSelectedParts(newSelectedParts);

    //         // Dispatch the action to update the AppStateContext
    //         appStateContext?.dispatch({
    //             type: 'UPDATE_SELECTED_PARTS',
    //             payload: newSelectedParts,
    //         });
    //     }
    // };

    const typeDropdownOptions = [
        { key: 'Code', text: 'Code' },
        { key: 'Agreed Procedure', text: 'Agreed Procedure' },
        { key: 'Appendice', text: 'Appendice' },
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
        { key: 'typesHeader', text: 'Types', itemType: DropdownMenuItemType.Header },
        ...typeDropdownOptions,
        { key: 'divider_1', text: '-', itemType: DropdownMenuItemType.Divider },
        { key: 'rulesHeader', text: 'Rules', itemType: DropdownMenuItemType.Header },
        ...rulesDropdownOptions,
        { key: 'divider_2', text: '-', itemType: DropdownMenuItemType.Divider },
        { key: 'partsHeader', text: 'Parts', itemType: DropdownMenuItemType.Header },
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
    //     dropdownItemHeader: {
    //         backgroundColor: '#122140' ,
    //         color: '#ffffff',
    //         selectors: {
    //             '&:hover': {
    //                 color: '#ffffff', // Different text color when hovered
    //             }
    //         }
    //     },
    //     dropdownItemsWrapper: { 
    //         backgroundColor: '#122140' ,
    //         color: '#ffffff',
    //     }, // Assuming you want to style the wrapper
    //     title: { 
    //         backgroundColor: '#122140', 
    //         color: '#ffffff',
    //         selectors: {
    //             '&:hover': {
    //                 backgroundColor: '#122140', 
    //                 color: '#ffffff',
    //             }
    //         }
    //     }, // Style for the title
    //     dropdownItem: {
    //         color: '#8795a2', // Text color for the dropdown items
    //         selectors: {
    //             '&:hover': {
    //                 backgroundColor: '#ffffff', // Different background color when hovered
    //                 color: '#0e2b45', // Different text color when hovered
    //             }
    //         }
    //     },
    //     dropdownItemSelected: {
    //         backgroundColor: '#0e2b45', color: '#ffffff', // Styles for selected items
    //     }
    };

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
                            placeholder="Select an option"
                            multiSelect
                            options={combinedOptions}
                            onChange={onDropdownChange}
                            styles={dropdownStyles}
                            // ... other props
                        />
                        {/* <Dropdown
                            placeholder="Select Document Type to filter by"
                            multiSelect
                            options={typeDropdownOptions}
                            selectedKeys={selectedTypes}
                            onChange={onTypesDropdownChange}
                            styles={dropdownStyles} // Adjust width as needed
                        />
                        <Dropdown
                            placeholder="Select Rules Set to filter by"
                            multiSelect
                            options={rulesDropdownOptions}
                            selectedKeys={selectedRules}
                            onChange={onRulesDropdownChange}
                            styles={{ dropdown: { width: 250 } }} // Adjust width as needed
                        />
                        <Dropdown
                            placeholder="Select Trading Settle Code Part to filter by"
                            multiSelect
                            options={partsDropdownOptions}
                            selectedKeys={selectedParts}
                            onChange={onPartsDropdownChange}
                            styles={{ dropdown: { width: 250 } }} // Adjust width as needed
                        /> */}
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
