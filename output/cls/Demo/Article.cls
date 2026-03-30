Class Demo.Article Extends %Persistent
{

/// Article headline
Property Title As %String(MAXLEN = 500) [ Required ];

/// URL-safe identifier
Property Slug As %String(MAXLEN = 200) [ Required ];

/// Full article body text
Property Body As %String;

/// View counter
Property Views As %Integer;

Property Published As %Boolean;

Storage Default
{
<Data name="ArticleDefaultData">
<Value name="1">
<Value>%%CLASSNAME</Value>
</Value>
<Value name="2">
<Value>Title</Value>
</Value>
<Value name="3">
<Value>Slug</Value>
</Value>
<Value name="4">
<Value>Body</Value>
</Value>
<Value name="5">
<Value>Views</Value>
</Value>
<Value name="6">
<Value>Published</Value>
</Value>
</Data>
<DataLocation>^Demo.ArticleD</DataLocation>
<DefaultData>ArticleDefaultData</DefaultData>
<ExtentSize>1</ExtentSize>
<IdLocation>^Demo.ArticleD</IdLocation>
<IndexLocation>^Demo.ArticleI</IndexLocation>
<Property name="%%CLASSNAME">
<AverageFieldSize>2</AverageFieldSize>
<OutlierSelectivity>.999999:</OutlierSelectivity>
<Selectivity>0.0001%</Selectivity>
</Property>
<Property name="%%ID">
<AverageFieldSize>3</AverageFieldSize>
<Selectivity>1</Selectivity>
</Property>
<Property name="Body">
<AverageFieldSize>5</AverageFieldSize>
<OutlierSelectivity>.999999:"..."</OutlierSelectivity>
<Selectivity>0.0001%</Selectivity>
</Property>
<Property name="Published">
<AverageFieldSize>2</AverageFieldSize>
<OutlierSelectivity>.999999:</OutlierSelectivity>
<Selectivity>0.0001%</Selectivity>
</Property>
<Property name="Slug">
<AverageFieldSize>16</AverageFieldSize>
<OutlierSelectivity>.999999:"hello-iris-orm"</OutlierSelectivity>
<Selectivity>0.0001%</Selectivity>
</Property>
<Property name="Title">
<AverageFieldSize>16</AverageFieldSize>
<OutlierSelectivity>.999999:"Hello iris_orm"</OutlierSelectivity>
<Selectivity>0.0001%</Selectivity>
</Property>
<Property name="Views">
<AverageFieldSize>3</AverageFieldSize>
<OutlierSelectivity>.999999:1</OutlierSelectivity>
<Selectivity>0.0001%</Selectivity>
</Property>
<SQLMap name="IDKEY">
<BlockCount>-4</BlockCount>
</SQLMap>
<StreamLocation>^Demo.ArticleS</StreamLocation>
<Type>%Storage.Persistent</Type>
}

}
