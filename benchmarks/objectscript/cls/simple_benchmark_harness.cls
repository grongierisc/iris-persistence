Class Bench.SimpleBenchmarkHarness Extends %RegisteredObject
{

ClassMethod TickCount() As %Double [ Private ]
{
    Set ts = $ZTIMESTAMP
    Quit (+$PIECE(ts,",",1) * 86400) + (+$PIECE(ts,",",2))
}

ClassMethod ElapsedSeconds(start As %Double) As %Double [ Private ]
{
    Quit ..TickCount() - start
}

ClassMethod SelectIds(sqlTableName As %String) As %String
{
    
    Set ids = ..SelectIdsArray(sqlTableName)
    If ids="" {
        Quit ""
    }
    Quit ids.%ToJSON()
}

ClassMethod SelectIdsArray(sqlTableName As %String) As %DynamicArray [ Private ]
{
    #; do $SYSTEM.SQL.Purge()
    Set stmt = ##class(%SQL.Statement).%New()
    Set sc = stmt.%Prepare("SELECT ID FROM "_sqlTableName_" ORDER BY ID")
    If '$SYSTEM.Status.IsOK(sc) {
        Do $SYSTEM.OBJ.DisplayError(sc)
        Quit ""
    }

    Set rset = stmt.%Execute()
    Set ids = ##class(%DynamicArray).%New()
    While rset.%Next() {
        Do ids.%Push(rset.%Get("ID"))
    }
    Quit ids
}

ClassMethod Run(sqlTableName As %String, count As %Integer = 500) As %String
{
    Set stmt = ##class(%SQL.Statement).%New()
    Set sc = stmt.%Prepare("DELETE FROM "_sqlTableName)
    If '$SYSTEM.Status.IsOK(sc) {
        Do $SYSTEM.OBJ.DisplayError(sc)
        Quit ""
    }
    Set rset = stmt.%Execute()

    Set start = ..TickCount()
    For i=1:1:count {
        Set obj = ##class(Bench.SimpleBenchmarkRecord).%New()
        Set obj.Name = "name-" _ (i - 1)
        Set obj.Category = "group-" _ ((i - 1) # 10)
        Set obj.Quantity = i - 1
        Set obj.Price = (i - 1) / 10.0
        Set obj.Active = ((i - 1) # 2) = 0
        Set sc = obj.%Save()
        If '$SYSTEM.Status.IsOK(sc) {
            Do $SYSTEM.OBJ.DisplayError(sc)
            Return
        }
        Set ids(i) = obj.%Id()
    }
    Set writeSeconds = ..ElapsedSeconds(start)

   

    Set start = ..TickCount()
    For i=1:1:count {
        Set obj = ##class(Bench.SimpleBenchmarkRecord).%OpenId(ids(i))
        Set sink = obj.Name
        Set sink = obj.Category
        Set sink = obj.Quantity
        Set sink = obj.Price
        Set sink = obj.Active
    }
    Set readSeconds = ..ElapsedSeconds(start)

    Set start = ..TickCount()
    Set ids = ..SelectIdsArray(sqlTableName)
    If ids="" {
        Quit ""
    }
    Set rowCount = ids.%Size()
    For i=0:1:(rowCount-1) {
        Set readId = ids.%Get(i)
        Set obj = ##class(Bench.SimpleBenchmarkRecord).%OpenId(readId)
        Set sink = obj.Name
        Set sink = obj.Category
        Set sink = obj.Quantity
        Set sink = obj.Price
        Set sink = obj.Active
    }
    Set fetchAllSeconds = ..ElapsedSeconds(start)

    Set result = ##class(%DynamicObject).%New()
    Do result.%Set("rows", count)
    Do result.%Set("fetched_rows", rowCount)
    Do result.%Set("write_seconds", writeSeconds)
    Do result.%Set("read_seconds", readSeconds)
    Do result.%Set("fetch_all_seconds", fetchAllSeconds)
    Quit result.%ToJSON()
}

}
